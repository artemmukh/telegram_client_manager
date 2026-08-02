import logging
from datetime import date, datetime

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message

from bot.config.clinic_instances import DATEPARSER_BY_INSTANCE as DATA_PARSE_MODE
from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError
from bot.handlers.utils.admin_utils.appointment_calendar_helpers import (
    clamp_month_to_range,
    format_month_label,
)
from bot.handlers.utils.admin_utils.input_helpers import ask_full_name
from bot.keyboards.admin.record_management_kb.appointment_browser_kb import appointment_calendar_kb
from bot.keyboards.admin.record_management_kb.appointment_kb import back_to_records_kb
from bot.keyboards.admin.record_management_kb.appointment_slot_kb import (
    appointment_slot_grid_kb,
    occupied_slot_card_kb,
)
from bot.keyboards.client.booking_kb import booking_day_kb, booking_doctor_kb
from bot.models.appointment import Appointment
from bot.services.utils.date_parser import (
    RESCHEDULE_NEGOTIATION_NOTE,
    build_reschedule_proposal_line,
    format_appointment_card_datetime,
    format_datetime_for_confirmation,
    get_current_tashkent_datetime,
    parse_ru_datetime,
)
from bot.states.admin.record_management.appointment_states import AppointmentCreationStates
from bot.utils.appointment_enums import APPOINTMENT_STATUS_LABELS, AppointmentStatus, CreatedBy
from bot.validators.validators import (
    validate_price,
    validate_purpose,
)

logger = logging.getLogger(__name__)

_DATETIME_INPUT_PROMPT = {
    "ru": (
        "Введите дату и время на русском языке:\n\n"
        "✅ Примеры правильного ввода:\n"
        "• завтра в 3 часа (→ 15:00)\n"
        "• завтра в 2 часа (→ 14:00, днём)\n"
        "• среда в 14:00\n"
        "• в пятницу в 2 часа дня (→ 14:00)\n"
        "• 13 сентября 15:30\n"
        "• через 2 часа\n"
        "• в 10 часов утра\n"
        "• в 8 часов вечера\n"
        "❌ Что не работает:\n"
        "• просто время без даты (нужна дата)\n"
        "• английский язык\n"
        "• 'через 2 часов' (правильно 'через 2 часа')"
    ),
    "uz": (
        "Sana va vaqtni rus tilida kiriting:\n\n"
        "✅ To'g'ri kiritish namunalari:\n"
        "• завтра в 3 часа (→ 15:00)\n"
        "• завтра в 2 часа (→ 14:00, kunduzi)\n"
        "• среда в 14:00\n"
        "• в пятницу в 2 часа дня (→ 14:00)\n"
        "• 13 сентября 15:30\n"
        "• через 2 часа\n"
        "• в 10 часов утра\n"
        "• в 8 часов вечера\n"
        "❌ Ishlamaydi:\n"
        "• sanasiz faqat vaqt (sana kerak)\n"
        "• ingliz tili\n"
        "• 'через 2 часов' (to'g'risi 'через 2 часа')"
    ),
}

_APPOINTMENT_CARD_LABELS = {
    "ru": {
        "confirm_title": "Проверьте данные записи:",
        "clinic": "Клиника",
        "client_name": "Имя клиента",
        "client": "Клиент",
        "phone": "Телефон",
        "doctor_phone": "Телефон врача",
        "datetime": "Дата и время",
        "time": "Время",
        "purpose": "Услуга",
        "status": "Статус",
        "doctor": "Врач",
        "price": "Цена",
        "created_at": "Создана",
        "appointment_number": "Запись №",
        "not_specified": "—",
    },
    "uz": {
        "confirm_title": "Yozuv ma'lumotlarini tekshiring:",
        "clinic": "Klinika",
        "client_name": "Mijoz ismi",
        "client": "Mijoz",
        "phone": "Telefon",
        "doctor_phone": "Shifokor telefoni",
        "datetime": "Sana va vaqt",
        "time": "Vaqt",
        "purpose": "Xizmat",
        "status": "Holati",
        "doctor": "Shifokor",
        "price": "Narx",
        "created_at": "Yaratilgan",
        "appointment_number": "Yozuv №",
        "not_specified": "—",
    },
}

_APPOINTMENTS_LIST_TOTAL = {
    "ru": "всего",
    "uz": "jami",
}

_APPOINTMENTS_BY_PHONE = {
    "ru": "Записи по номеру {phone} (всего: {total}):",
    "uz": "{phone} raqami bo'yicha yozuvlar (jami: {total}):",
}

_FAILED_TO_PARSE_DATETIME = {
    "ru": (
        "Не смог распознать дату и время.\n"
        "Попробуйте снова:\n"
        "• завтра в 3 часа\n"
        "• 13 сентября 15:30\n"
        "• в понедельник в 14:00"
    ),
    "uz": (
        "Sana va vaqtni aniqlab bo'lmadi.\n"
        "Qaytadan urinib ko'ring:\n"
        "• завтра в 3 часа\n"
        "• 13 сентября 15:30\n"
        "• в понедельник в 14:00"
    ),
}

_CHOOSE_DAY_PROMPT = {
    "ru": "Выберите день записи:",
    "uz": "Qabul kunini tanlang:",
}

_BACK_TO_RECORDS_LABEL = {
    "ru": "⬅️ К записям",
    "uz": "⬅️ Yozuvlarga",
}

_CANCEL_LABEL = {
    "ru": "❌ Отменить",
    "uz": "❌ Bekor qilish",
}

_CHOOSE_TIME_FOR_DAY = {
    "ru": "Выберите время на {day}:",
    "uz": "{day} uchun vaqtni tanlang:",
}

_APPOINTMENT_NOT_FOUND = {
    "ru": "Запись не найдена.",
    "uz": "Yozuv topilmadi.",
}

_INVALID_TIME = {
    "ru": "Некорректное время, попробуйте ещё раз.",
    "uz": "Vaqt noto'g'ri, qaytadan urinib ko'ring.",
}

_PROPOSE_DATETIME_TO_CLIENT = {
    "ru": "Предложить клиенту время: {old} → {new}?",
    "uz": "Mijozga vaqt taklif qilinsinmi: {old} → {new}?",
}

_CHOOSE_DOCTOR_PROMPT = {
    "ru": "Выберите врача:",
    "uz": "Shifokorni tanlang:",
}


def datetime_input_prompt(lang: str = "ru") -> str:
    return _DATETIME_INPUT_PROMPT.get(lang, _DATETIME_INPUT_PROMPT["ru"])


def choose_time_for_day_prompt(day_display: str, lang: str = "ru") -> str:
    return _CHOOSE_TIME_FOR_DAY.get(lang, _CHOOSE_TIME_FOR_DAY["ru"]).format(day=day_display)


def build_appointment_confirmation(data: dict, lang: str = "ru") -> str:
    labels = _APPOINTMENT_CARD_LABELS.get(lang, _APPOINTMENT_CARD_LABELS["ru"])
    display_datetime = data.get('appointment_datetime_display') or data.get('appointment_datetime', '')
    return "\n".join([
        labels["confirm_title"],
        "",
        f"{labels['clinic']}: {data.get('clinic_name', '')}",
        f"{labels['client_name']}: {data.get('full_name', '')}",
        f"{labels['phone']}: {data.get('phone', '')}",
        f"{labels['datetime']}: {display_datetime}",
        f"{labels['purpose']}: {data.get('purpose', '')}",
        f"{labels['status']}: {APPOINTMENT_STATUS_LABELS[AppointmentStatus.PENDING]}",
    ])


def build_appointment_card(appointment: Appointment, lang: str = "ru") -> str:
    labels = _APPOINTMENT_CARD_LABELS.get(lang, _APPOINTMENT_CARD_LABELS["ru"])
    lines = [f"{labels['appointment_number']}{appointment.id}"]

    if appointment.clinic_name:
        lines.append(f"{labels['clinic']}: {appointment.clinic_name}")


    if appointment.client_full_name:
        lines.append(f"{labels['client']}: {appointment.client_full_name}")

    if appointment.client_phone:
        lines.append(f"{labels['phone']}: {appointment.client_phone}")

    if appointment.doctor_full_name and appointment.doctor_is_doctor:
        lines.append(f"{labels['doctor']}: {appointment.doctor_full_name}")
        lines.append(f"{labels['doctor_phone']}: {appointment.doctor_phone or labels['not_specified']}")

    if appointment.price:
        lines.append(f"{labels['price']}: {appointment.price}")


    lines += [
        f"{labels['time']}: {format_appointment_card_datetime(appointment.datetime)}",
        f"{labels['purpose']}: {appointment.purpose}",
        f"{labels['status']}: {APPOINTMENT_STATUS_LABELS.get(appointment.status, appointment.status.value)}",
    ]

    proposal_line = build_reschedule_proposal_line(appointment, viewer=CreatedBy.ADMIN)
    if proposal_line is not None:
        lines.append(proposal_line)
        lines.append(RESCHEDULE_NEGOTIATION_NOTE)

    if appointment.price is not None:
        lines.append(f"{labels['price']}: {appointment.price}")

    if appointment.created_at:
        lines.append(f"{labels['created_at']}: {appointment.created_at}")

    return "\n".join(lines)


def format_appointments_list(title: str, appointments: list[Appointment], lang: str = "ru") -> str:
    total_label = _APPOINTMENTS_LIST_TOTAL.get(lang, _APPOINTMENTS_LIST_TOTAL["ru"])
    lines = [f"{title} ({total_label}: {len(appointments)}):", ""]
    for appointment in appointments:
        lines.append(build_appointment_card(appointment, lang))
        lines.append("")
    return "\n".join(lines).strip()


async def show_appointments_with_actions(
    message: Message,
    phone: str,
    appointments: list[Appointment],
    keyboard_factory,
    lang: str = "ru",
) -> None:
    await message.answer(
        _APPOINTMENTS_BY_PHONE.get(lang, _APPOINTMENTS_BY_PHONE["ru"]).format(phone=phone, total=len(appointments))
    )

    for appointment in appointments:
        await message.answer(
            build_appointment_card(appointment, lang),
            reply_markup=keyboard_factory(appointment.id),
        )


async def datetime_processing(message: Message, state: FSMContext, next_state: State, lang: str = "ru") -> bool:

    raw_text = message.text.strip()
    parsed_dt = parse_ru_datetime(raw_text)

    if parsed_dt is None:
        logger.info("Failed to parse admin-typed datetime input: %r", raw_text)
        await message.answer(_FAILED_TO_PARSE_DATETIME.get(lang, _FAILED_TO_PARSE_DATETIME["ru"]))
        return False

    logger.info("Parsed admin-typed datetime input %r as %s", raw_text, parsed_dt)

    await state.update_data(
        appointment_datetime_parsed=parsed_dt,
        appointment_datetime_display=format_datetime_for_confirmation(parsed_dt)
    )
    await state.set_state(next_state)
    return True


async def purpose_processing(message: Message, state: FSMContext, next_state: State, lang: str = "ru") -> bool:
    try:
        value = validate_purpose(message.text.strip())
    except ValidationError as e:
        await message.answer(e.localized(lang))
        return False

    await state.update_data(purpose=value)
    await state.set_state(next_state)
    return True


async def price_processing(message: Message, state: FSMContext, next_state: State, lang: str = "ru") -> bool:
    try:
        value = validate_price(message.text.strip())
    except ValidationError as e:
        await message.answer(e.localized(lang))
        return False

    await state.update_data(price=value)
    await state.set_state(next_state)
    return True


async def _ensure_staff_user_id(appt_mng, state: FSMContext, admin_telegram_id: int) -> None:
    """MM's slot picker needs a doctor id to look up available slots. Mirror
    AppointmentManagement.create_appointment's own fallback of defaulting to
    the acting admin's own User.ID when no doctor was explicitly chosen
    (e.g. a doctor-scoped admin with no doctor picker in front of them)."""
    data = await state.get_data()
    if data.get("staff_user_id") is not None:
        return

    admin_user = await appt_mng.get_user_by_telegram_id(admin_telegram_id)
    if admin_user is None:
        logger.warning(
            "Could not resolve acting admin's own User.ID for MM slot picker "
            "fallback (telegram_id=%s)", admin_telegram_id,
        )
        return

    await state.update_data(staff_user_id=admin_user.ID)


async def _send_day_selection(appt_mng, state: FSMContext, week_offset: int, send, lang: str = "ru") -> None:
    reference = get_current_tashkent_datetime().date()
    days = await appt_mng.get_working_days(reference, week_offset)

    data = await state.get_data()
    min_week_offset = data.get("min_week_offset", week_offset)
    can_go_back = week_offset > min_week_offset
    can_go_forward = bool(await appt_mng.get_working_days(reference, week_offset + 1))

    await state.update_data(week_offset=week_offset)
    await state.set_state(AppointmentCreationStates.choose_day)

    await send(
        _CHOOSE_DAY_PROMPT.get(lang, _CHOOSE_DAY_PROMPT["ru"]),
        booking_day_kb(
            days, week_offset, can_go_back, can_go_forward,
            cancel_callback_data="back_to_main_records", lang=lang,
        ),
    )


async def render_day_selection(
    appt_mng, callback_query: CallbackQuery, state: FSMContext, week_offset: int, lang: str = "ru",
) -> None:
    async def send(text: str, reply_markup) -> None:
        await callback_query.message.edit_text(text, reply_markup=reply_markup)

    await _send_day_selection(appt_mng, state, week_offset, send, lang)
    await callback_query.answer()


async def render_day_selection_start(
    appt_mng, callback_query: CallbackQuery, state: FSMContext, lang: str = "ru",
) -> None:
    await _ensure_staff_user_id(appt_mng, state, callback_query.from_user.id)
    reference = get_current_tashkent_datetime().date()
    start_offset = await appt_mng.find_first_available_week_offset(reference)
    await state.update_data(min_week_offset=start_offset)
    await render_day_selection(appt_mng, callback_query, state, start_offset, lang)


async def render_day_selection_start_from_message(
    appt_mng, message: Message, state: FSMContext, lang: str = "ru",
) -> None:
    await _ensure_staff_user_id(appt_mng, state, message.from_user.id)
    reference = get_current_tashkent_datetime().date()
    start_offset = await appt_mng.find_first_available_week_offset(reference)
    await state.update_data(min_week_offset=start_offset)

    async def send(text: str, reply_markup) -> None:
        await message.answer(text, reply_markup=reply_markup)

    await _send_day_selection(appt_mng, state, start_offset, send, lang)


async def _send_calendar_month(
    state: FSMContext, year: int, month: int, send,
    choose_day_state: State = AppointmentCreationStates.choose_day,
    back_callback_data: str = "back_to_main_records",
    back_label: str | None = None,
    lang: str = "ru",
) -> None:
    await state.update_data(calendar_year=year, calendar_month=month)
    await state.set_state(choose_day_state)

    if back_label is None:
        back_label = _BACK_TO_RECORDS_LABEL.get(lang, _BACK_TO_RECORDS_LABEL["ru"])

    await send(
        f"📅 {format_month_label(year, month, lang)}",
        appointment_calendar_kb(
            year, month, back_callback_data=back_callback_data, back_label=back_label, lang=lang,
        ),
    )


async def render_calendar_month(
    callback_query: CallbackQuery, state: FSMContext, year: int, month: int,
    choose_day_state: State = AppointmentCreationStates.choose_day,
    back_callback_data: str = "back_to_main_records",
    back_label: str | None = None,
    lang: str = "ru",
) -> None:
    async def send(text: str, reply_markup) -> None:
        await callback_query.message.edit_text(text, reply_markup=reply_markup)

    await _send_calendar_month(state, year, month, send, choose_day_state, back_callback_data, back_label, lang)
    await callback_query.answer()


async def render_calendar_start(
    appt_mng, callback_query: CallbackQuery, state: FSMContext,
    choose_day_state: State = AppointmentCreationStates.choose_day,
    back_callback_data: str = "back_to_main_records",
    back_label: str | None = None,
    lang: str = "ru",
) -> None:
    await _ensure_staff_user_id(appt_mng, state, callback_query.from_user.id)
    today = get_current_tashkent_datetime().date()
    year, month = clamp_month_to_range(today.year, today.month)
    await render_calendar_month(
        callback_query, state, year, month, choose_day_state, back_callback_data, back_label, lang,
    )


async def render_calendar_start_from_message(
    appt_mng, message: Message, state: FSMContext, lang: str = "ru",
) -> None:
    await _ensure_staff_user_id(appt_mng, state, message.from_user.id)
    today = get_current_tashkent_datetime().date()
    year, month = clamp_month_to_range(today.year, today.month)

    async def send(text: str, reply_markup) -> None:
        await message.answer(text, reply_markup=reply_markup)

    await _send_calendar_month(state, year, month, send, lang=lang)


def propose_calendar_back_target(cb_class, appointment_id: int, lang: str = "ru") -> tuple[str, str]:
    return (
        cb_class(action="cancel_propose", appointment_id=appointment_id).pack(),
        _CANCEL_LABEL.get(lang, _CANCEL_LABEL["ru"]),
    )


async def render_propose_calendar_start(
    callback_query: CallbackQuery, state: FSMContext, appointment_id: int,
    choose_day_state: State, cb_class, today: date, lang: str = "ru",
) -> None:
    await callback_query.answer('')
    year, month = clamp_month_to_range(today.year, today.month)
    back_callback_data, back_label = propose_calendar_back_target(cb_class, appointment_id, lang)
    await render_calendar_month(
        callback_query, state, year, month,
        choose_day_state=choose_day_state,
        back_callback_data=back_callback_data, back_label=back_label, lang=lang,
    )


async def render_propose_slot_grid(
    appt_mng, callback_query: CallbackQuery, state: FSMContext, day_iso: str, choose_slot_state: State, now: datetime,
    lang: str = "ru",
) -> bool:
    day = date.fromisoformat(day_iso)
    data = await state.get_data()
    occupancy = await appt_mng.get_day_slot_occupancy(
        data["staff_user_id"], day, now, exclude_appointment_id=data["appointment_id"],
    )

    if not occupancy:
        return False

    await state.update_data(day_iso=day_iso)
    await state.set_state(choose_slot_state)
    await callback_query.message.edit_text(
        choose_time_for_day_prompt(day.strftime('%d.%m.%Y'), lang),
        reply_markup=appointment_slot_grid_kb(occupancy, cancel_callback_data="admin_book_back_to_day", lang=lang),
    )
    return True


async def render_occupied_slot_card(
    appt_mng, callback_query: CallbackQuery, appointment_id: int, lang: str = "ru",
) -> None:
    appointment = await appt_mng.get_appointment_by_id(appointment_id)
    if appointment is None:
        await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
        return

    await callback_query.answer('')
    await callback_query.message.edit_text(
        build_appointment_card(appointment, lang),
        reply_markup=occupied_slot_card_kb(lang=lang),
    )


async def apply_picked_propose_slot(
    callback_query: CallbackQuery, callback_data, state: FSMContext,
    confirm_state: State, confirm_kb_builder, lang: str = "ru",
) -> None:
    try:
        datetime.strptime(callback_data.slot, "%H:%M")
    except ValueError:
        await callback_query.answer(_INVALID_TIME.get(lang, _INVALID_TIME["ru"]), show_alert=True)
        return

    data = await state.get_data()
    appointment_datetime = f"{data['day_iso']} {callback_data.slot}"
    parsed_dt = datetime.strptime(appointment_datetime, "%Y-%m-%d %H:%M")
    new_display = format_datetime_for_confirmation(parsed_dt)

    await state.update_data(appointment_datetime_parsed=parsed_dt, appointment_datetime_display=new_display)
    await state.set_state(confirm_state)

    old_display = format_datetime_for_confirmation(datetime.fromisoformat(data["old_datetime"]))
    await callback_query.message.edit_text(
        _PROPOSE_DATETIME_TO_CLIENT.get(lang, _PROPOSE_DATETIME_TO_CLIENT["ru"]).format(
            old=old_display, new=new_display,
        ),
        reply_markup=confirm_kb_builder(data["appointment_id"]),
    )
    await callback_query.answer()


async def begin_appointment_creation(
    appt_mng, callback_query: CallbackQuery, state: FSMContext, *,
    instance: str,
    full_name: str | None = None, phone: str | None = None,
    origin_client_id: int | None = None, origin_mode: str | None = None,
    origin_page: int | None = None, origin_search_data: dict | None = None,
    lang: str = "ru",
) -> None:
    await state.clear()

    try:
        clinic = await appt_mng.get_admin_clinic(callback_query.from_user.id)
    except BotException as e:
        await callback_query.answer(e.localized(lang), show_alert=True)
        return

    await state.update_data(clinic_name=clinic.name)

    if full_name is not None and phone is not None:
        preselect_data = {
            "client_preselected": True,
            "full_name": full_name,
            "phone": phone,
        }
        if origin_client_id is not None:
            preselect_data["origin_client_id"] = origin_client_id
        if origin_mode is not None:
            preselect_data["origin_mode"] = origin_mode
        if origin_page is not None:
            preselect_data["origin_page"] = origin_page
        if origin_search_data is not None:
            preselect_data["origin_search_data"] = origin_search_data
        await state.update_data(**preselect_data)

    doctors = await appt_mng.list_clinic_doctors_for_creation(callback_query.from_user.id)
    if doctors:
        await state.update_data(staff_options={str(d.ID): d.full_name for d in doctors})
        await state.set_state(AppointmentCreationStates.choose_doctor)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            _CHOOSE_DOCTOR_PROMPT.get(lang, _CHOOSE_DOCTOR_PROMPT["ru"]),
            reply_markup=booking_doctor_kb(doctors, cancel_callback_data="back_to_main_records", lang=lang),
        )
        return

    if full_name is not None and phone is not None:
        if DATA_PARSE_MODE.get(instance) == "slots":
            await callback_query.answer('')
            await render_calendar_start(appt_mng, callback_query, state, lang=lang)
            return

        await state.set_state(AppointmentCreationStates.appointment_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            datetime_input_prompt(lang),
            reply_markup=back_to_records_kb(lang=lang),
        )
        return

    await ask_full_name(
        callback_query, state, AppointmentCreationStates.client_full_name,
        reply_markup=back_to_records_kb(lang=lang), lang=lang,
    )
