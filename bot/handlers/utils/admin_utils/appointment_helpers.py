import logging

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message

from bot.config.clinic_instances import DATEPARSER_BY_INSTANCE as DATA_PARSE_MODE
from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError
from bot.handlers.utils.admin_utils.input_helpers import ask_full_name
from bot.keyboards.admin.record_management_kb.appointment_kb import back_to_records_kb
from bot.keyboards.client.booking_kb import booking_day_kb, booking_doctor_kb
from bot.models.appointment import Appointment
from bot.services.utils.date_parser import (
    RESCHEDULE_NEGOTIATION_NOTE,
    build_reschedule_proposal_line,
    format_appointment_card_datetime,
    format_datetime_for_display,
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

DATETIME_INPUT_PROMPT = (
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
    "• в 2 часа ночи\n\n"
    "❌ Что не работает:\n"
    "• просто время без даты (нужна дата)\n"
    "• английский язык\n"
    "• 'через 2 часов' (правильно 'через 2 часа')"
)


def build_appointment_confirmation(data: dict) -> str:
    display_datetime = data.get('appointment_datetime_display') or data.get('appointment_datetime', '')
    return "\n".join([
        "Проверьте данные записи:",
        "",
        f"Клиника: {data.get('clinic_name', '')}",
        f"Имя клиента: {data.get('full_name', '')}",
        f"Телефон: {data.get('phone', '')}",
        f"Дата и время: {display_datetime}",
        f"Услуга: {data.get('purpose', '')}",
        f"Статус: {APPOINTMENT_STATUS_LABELS[AppointmentStatus.PENDING]}",
    ])


def build_appointment_card(appointment: Appointment) -> str:
    lines = [f"Запись №{appointment.id}"]

    if appointment.clinic_name:
        lines.append(f"Клиника: {appointment.clinic_name}")

    if appointment.client_full_name:
        lines.append(f"Клиент: {appointment.client_full_name}")

    if appointment.client_phone:
        lines.append(f"Телефон: {appointment.client_phone}")

    if appointment.doctor_full_name and appointment.doctor_is_doctor:
        lines.append(f"Врач: {appointment.doctor_full_name}")
        lines.append(f"Телефон врача: {appointment.doctor_phone or '—'}")

    lines += [
        f"Время: {format_appointment_card_datetime(appointment.datetime)}",
        f"Услуга: {appointment.purpose}",
        f"Статус: {APPOINTMENT_STATUS_LABELS.get(appointment.status, appointment.status.value)}",
    ]

    proposal_line = build_reschedule_proposal_line(appointment, viewer=CreatedBy.ADMIN)
    if proposal_line is not None:
        lines.append(proposal_line)
        lines.append(RESCHEDULE_NEGOTIATION_NOTE)

    if appointment.price is not None:
        lines.append(f"Цена: {appointment.price}")

    if appointment.created_at:
        lines.append(f"Создана: {appointment.created_at}")

    return "\n".join(lines)


def format_appointments_list(title: str, appointments: list[Appointment]) -> str:
    lines = [f"{title} (всего: {len(appointments)}):", ""]
    for appointment in appointments:
        lines.append(build_appointment_card(appointment))
        lines.append("")
    return "\n".join(lines).strip()


async def show_appointments_with_actions(
    message: Message,
    phone: str,
    appointments: list[Appointment],
    keyboard_factory,
) -> None:
    await message.answer(f"Записи по номеру {phone} (всего: {len(appointments)}):")

    for appointment in appointments:
        await message.answer(
            build_appointment_card(appointment),
            reply_markup=keyboard_factory(appointment.id),
        )


async def datetime_processing(message: Message, state: FSMContext, next_state: State) -> bool:

    parsed_dt = parse_ru_datetime(message.text.strip())

    if parsed_dt is None:
        await message.answer(
            "Не смог распознать дату и время.\n"
            "Попробуйте снова:\n"
            "• завтра в 3 часа\n"
            "• 13 сентября 15:30\n"
            "• в понедельник в 14:00"
        )
        return False

    await state.update_data(
        appointment_datetime_parsed=parsed_dt,
        appointment_datetime_display=format_datetime_for_display(parsed_dt)
    )
    await state.set_state(next_state)
    return True


async def purpose_processing(message: Message, state: FSMContext, next_state: State) -> bool:
    try:
        value = validate_purpose(message.text.strip())
    except ValidationError as e:
        await message.answer(str(e))
        return False

    await state.update_data(purpose=value)
    await state.set_state(next_state)
    return True


async def price_processing(message: Message, state: FSMContext, next_state: State) -> bool:
    try:
        value = validate_price(message.text.strip())
    except ValidationError as e:
        await message.answer(str(e))
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


async def _send_day_selection(appt_mng, state: FSMContext, week_offset: int, send) -> None:
    reference = get_current_tashkent_datetime().date()
    days = await appt_mng.get_working_days(reference, week_offset)

    data = await state.get_data()
    min_week_offset = data.get("min_week_offset", week_offset)
    can_go_back = week_offset > min_week_offset
    can_go_forward = bool(await appt_mng.get_working_days(reference, week_offset + 1))

    await state.update_data(week_offset=week_offset)
    await state.set_state(AppointmentCreationStates.choose_day)

    await send(
        "Выберите день записи:",
        booking_day_kb(days, week_offset, can_go_back, can_go_forward, cancel_callback_data="back_to_main_records"),
    )


async def render_day_selection(appt_mng, callback_query: CallbackQuery, state: FSMContext, week_offset: int) -> None:
    async def send(text: str, reply_markup) -> None:
        await callback_query.message.edit_text(text, reply_markup=reply_markup)

    await _send_day_selection(appt_mng, state, week_offset, send)
    await callback_query.answer()


async def render_day_selection_start(appt_mng, callback_query: CallbackQuery, state: FSMContext) -> None:
    await _ensure_staff_user_id(appt_mng, state, callback_query.from_user.id)
    reference = get_current_tashkent_datetime().date()
    start_offset = await appt_mng.find_first_available_week_offset(reference)
    await state.update_data(min_week_offset=start_offset)
    await render_day_selection(appt_mng, callback_query, state, start_offset)


async def render_day_selection_start_from_message(appt_mng, message: Message, state: FSMContext) -> None:
    await _ensure_staff_user_id(appt_mng, state, message.from_user.id)
    reference = get_current_tashkent_datetime().date()
    start_offset = await appt_mng.find_first_available_week_offset(reference)
    await state.update_data(min_week_offset=start_offset)

    async def send(text: str, reply_markup) -> None:
        await message.answer(text, reply_markup=reply_markup)

    await _send_day_selection(appt_mng, state, start_offset, send)


async def begin_appointment_creation(
    appt_mng, callback_query: CallbackQuery, state: FSMContext, *,
    instance: str,
    full_name: str | None = None, phone: str | None = None,
    origin_client_id: int | None = None, origin_mode: str | None = None,
    origin_page: int | None = None, origin_search_data: dict | None = None,
) -> None:
    await state.clear()

    try:
        clinic = await appt_mng.get_admin_clinic(callback_query.from_user.id)
    except BotException as e:
        await callback_query.answer(str(e), show_alert=True)
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
            "Выберите врача:",
            reply_markup=booking_doctor_kb(doctors, cancel_callback_data="back_to_main_records"),
        )
        return

    if full_name is not None and phone is not None:
        if DATA_PARSE_MODE.get(instance) == "slots":
            await callback_query.answer('')
            await render_day_selection_start(appt_mng, callback_query, state)
            return

        await state.set_state(AppointmentCreationStates.appointment_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            DATETIME_INPUT_PROMPT,
            reply_markup=back_to_records_kb(),
        )
        return

    await ask_full_name(callback_query, state, AppointmentCreationStates.client_full_name, reply_markup=back_to_records_kb())
