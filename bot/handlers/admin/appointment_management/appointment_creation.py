import logging
from datetime import date, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError, PhoneAlreadyExistsError
from bot.handlers.utils.admin_utils import appointment_helpers as ah
from bot.handlers.utils.admin_utils.appointment_calendar_helpers import clamp_calendar_date, clamp_month_to_range
from bot.handlers.utils.admin_utils.appointment_helpers import (
    build_appointment_confirmation,
    build_appointment_card,
    choose_time_for_day_prompt,
    datetime_input_prompt,
    datetime_processing,
    purpose_processing,
)
from bot.handlers.utils.admin_utils.confirmations import show_confirmation
from bot.handlers.utils.admin_utils.input_helpers import (
    ask_full_name,
    phone_processing,
    full_name_processing,
    edit_full_name,
    edit_phone,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import ApptCalendarDayCB, ApptCalendarMonthCB
from bot.keyboards.admin.record_management_kb.appointment_creation_cb import AdminOccupiedSlotCB
from bot.keyboards.admin.record_management_kb.appointment_kb import (
    appointment_confirm_kb,
    appointment_datetime_confirm_kb,
    client_creation_confirm_kb,
    back_to_records_kb,
)
from bot.keyboards.admin.record_management_kb.appointment_slot_kb import appointment_slot_grid_kb, occupied_slot_card_kb
from bot.keyboards.client.booking_cb import ClientBookDoctorCB, ClientBookSlotCB
from bot.models.user import User
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.utils.date_parser import format_datetime_for_db, format_datetime_for_display, get_current_tashkent_datetime
from bot.states.admin.record_management.appointment_states import AppointmentCreationStates
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.role import RoleFilter
from bot.validators.validators import SEARCH_NAME_PATTERN
from bot.config.clinic_instances import DATEPARSER_BY_INSTANCE as DATA_PARSE_MODE

logger = logging.getLogger(__name__)

_DEFAULT_DOCTOR_NAME = {
    "ru": "Врач",
    "uz": "Shifokor",
}

_ASK_CLIENT_PHONE = {
    "ru": "Введите номер телефона клиента:",
    "uz": "Mijoz telefon raqamini kiriting:",
}

_CLIENT_CREATED = {
    "ru": "✅ Клиент создан: {name}\n\n",
    "uz": "✅ Mijoz yaratildi: {name}\n\n",
}

_CLIENT_CREATION_ERROR = {
    "ru": "Ошибка создания клиента: {error}",
    "uz": "Mijoz yaratishda xatolik: {error}",
}

_DID_YOU_MEAN = {
    "ru": "Вы имели в виду: {value}?",
    "uz": "Nazarda tutdingizmi: {value}?",
}

_DATE_PROCESSING_ERROR = {
    "ru": "Ошибка: не удалось обработать дату. Попробуйте снова.",
    "uz": "Xatolik: sanani qayta ishlab bo'lmadi. Qaytadan urinib ko'ring.",
}

_ASK_PURPOSE = {
    "ru": "Опишите услугу (например: Консультация):",
    "uz": "Xizmatni yozing (masalan: Konsultatsiya):",
}

_ASK_PAIN_OR_PROBLEM = {
    "ru": "Опишите боль или проблему:",
    "uz": "Og'riq yoki muammoni yozing:",
}

_NO_SLOTS_FOR_DAY = {
    "ru": "На этот день нет доступных слотов.",
    "uz": "Bu kunga bo'sh vaqt yo'q.",
}

_APPOINTMENT_NOT_FOUND = {
    "ru": "Запись не найдена.",
    "uz": "Yozuv topilmadi.",
}

_INVALID_TIME = {
    "ru": "Некорректное время, попробуйте ещё раз.",
    "uz": "Vaqt noto'g'ri, qaytadan urinib ko'ring.",
}

_APPOINTMENT_CREATION_ERROR = {
    "ru": "Ошибка создания записи: {error}",
    "uz": "Yozuv yaratishda xatolik: {error}",
}

_APPOINTMENT_CREATED = {
    "ru": "Запись успешно создана!\n\n",
    "uz": "Yozuv muvaffaqiyatli yaratildi!\n\n",
}

_NOTIFICATION_SENT = {
    "ru": "\n✅ Уведомление отправлено клиенту",
    "uz": "\n✅ Mijozga xabar yuborildi",
}

_NOTIFICATION_FAILED = {
    "ru": "\n⚠️ Не удалось отправить уведомление клиенту",
    "uz": "\n⚠️ Mijozga xabar yuborilmadi",
}

_REMINDERS_SCHEDULED = {
    "ru": "\n⏰ Напоминания запланированы (24ч и 2ч перед приемом)",
    "uz": "\n⏰ Eslatmalar rejalashtirildi (qabuldan 24 va 2 soat oldin)",
}

_AUTO_COMPLETE_SCHEDULED = {
    "ru": "\n✅ Автозавершение: через 2ч после приема",
    "uz": "\n✅ Avtoyakunlash: qabuldan 2 soat keyin",
}


def create_admin_appointment_creation_router(instance:str,
    appointment_repo, user_repo, staff_repo, clinic_repo, client_management=None, notification_service=None,
    scheduler=None, client_clinic_repo=None
):
    router = Router()

    appt_mng = AppointmentManagement(
        appointment_repo, user_repo, staff_repo, clinic_repo, client_management,
        client_clinic_repository=client_clinic_repo,
    )

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    async def begin_appointment_creation(callback_query: CallbackQuery, state: FSMContext, lang: str = "ru"):
        await ah.begin_appointment_creation(appt_mng, callback_query, state, instance=instance, lang=lang)

    @router.callback_query(F.data == "create_record")
    async def start_create(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        await begin_appointment_creation(callback_query, state, current_user.language)

    @router.callback_query(AppointmentCreationStates.choose_doctor, ClientBookDoctorCB.filter())
    async def pick_doctor(
        callback_query: CallbackQuery, callback_data: ClientBookDoctorCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        data = await state.get_data()
        staff_options = data.get("staff_options", {})
        staff_name = staff_options.get(
            str(callback_data.staff_user_id), _DEFAULT_DOCTOR_NAME.get(lang, _DEFAULT_DOCTOR_NAME["ru"])
        )

        await state.update_data(staff_user_id=callback_data.staff_user_id, staff_name=staff_name)

        if data.get("client_preselected"):
            if DATA_PARSE_MODE.get(instance) == "slots":
                await callback_query.answer('')
                await ah.render_calendar_start(appt_mng, callback_query, state, lang=lang)
                return

            await state.set_state(AppointmentCreationStates.appointment_datetime)
            await callback_query.answer('')
            await callback_query.message.edit_text(
                datetime_input_prompt(lang), reply_markup=back_to_records_kb(lang=lang),
            )
            return

        await ask_full_name(
            callback_query, state, AppointmentCreationStates.client_full_name,
            reply_markup=back_to_records_kb(lang=lang), lang=lang,
        )

    @router.callback_query(F.data == "restart_appointment_create")
    async def restart_create(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        data = await state.get_data()
        if data.get("client_preselected"):
            await ah.begin_appointment_creation(
                appt_mng, callback_query, state,
                instance=instance,
                full_name=data.get("full_name"), phone=data.get("phone"),
                origin_client_id=data.get("origin_client_id"), origin_mode=data.get("origin_mode"),
                origin_page=data.get("origin_page"), origin_search_data=data.get("origin_search_data"),
                lang=lang,
            )
            return
        await begin_appointment_creation(callback_query, state, lang)

    @router.message(AppointmentCreationStates.client_full_name, F.text)
    async def get_name(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        if not await full_name_processing(message, state, AppointmentCreationStates.client_phone, re_pattern=SEARCH_NAME_PATTERN):
            return
        await message.answer(_ASK_CLIENT_PHONE.get(lang, _ASK_CLIENT_PHONE["ru"]), reply_markup=back_to_records_kb(lang=lang))

    @router.message(AppointmentCreationStates.client_phone, F.text)
    async def get_phone(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        if not await phone_processing(
            message, state, final_state=AppointmentCreationStates.confirm_create
        ):
            return

        data = await state.get_data()
        phone = data.get('phone')

        client = await appt_mng.find_client_by_phone(phone)

        if client:
            if DATA_PARSE_MODE.get(instance) == "slots":
                await ah.render_calendar_start_from_message(appt_mng, message, state, lang=lang)
                return

            await state.set_state(AppointmentCreationStates.appointment_datetime)
            await message.answer(
                datetime_input_prompt(lang),
                reply_markup=back_to_records_kb(lang=lang),
            )
        else:
            await show_confirmation(message, state, reply_markup=client_creation_confirm_kb(lang=lang))

    @router.callback_query(AppointmentCreationStates.confirm_create, F.data == "confirm_client_creation")
    async def handle_confirm_client_creation(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        data = await state.get_data()

        try:
            await appt_mng.check_or_create_client(
                callback_query.from_user.id,
                full_name=data['full_name'],
                phone=data['phone'],
            )
        except PhoneAlreadyExistsError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(
                _CLIENT_CREATION_ERROR.get(lang, _CLIENT_CREATION_ERROR["ru"]).format(error=e), show_alert=True,
            )
            return


        if DATA_PARSE_MODE.get(instance) == "slots":
            await callback_query.answer('')
            await ah.render_calendar_start(appt_mng, callback_query, state, lang=lang)
            return

        await state.set_state(AppointmentCreationStates.appointment_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            _CLIENT_CREATED.get(lang, _CLIENT_CREATED["ru"]).format(name=data['full_name']) + datetime_input_prompt(lang),
            reply_markup=back_to_records_kb(lang=lang),
        )

    @router.callback_query(AppointmentCreationStates.confirm_create, F.data == "edit_client_name_in_appointment")
    async def handle_edit_client_name(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        await edit_full_name(
            callback_query, state, AppointmentCreationStates.edit_full_name,
            reply_markup=back_to_records_kb(lang=lang), lang=lang,
        )

    @router.message(AppointmentCreationStates.edit_full_name, F.text)
    async def process_edit_client_name(message: Message, state: FSMContext, current_user: User):
        if not await full_name_processing(message, state, AppointmentCreationStates.confirm_create, re_pattern=SEARCH_NAME_PATTERN):
            return
        await show_confirmation(message, state, reply_markup=client_creation_confirm_kb(lang=current_user.language))

    @router.callback_query(AppointmentCreationStates.confirm_create, F.data == "edit_client_phone_in_appointment")
    async def handle_edit_client_phone(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        await edit_phone(
            callback_query, state, AppointmentCreationStates.edit_phone,
            reply_markup=back_to_records_kb(lang=lang), lang=lang,
        )

    @router.message(AppointmentCreationStates.edit_phone, F.text)
    async def process_edit_client_phone(message: Message, state: FSMContext, current_user: User):
        if not await phone_processing(
            message, state, final_state=AppointmentCreationStates.confirm_create
        ):
            return
        await show_confirmation(message, state, reply_markup=client_creation_confirm_kb(lang=current_user.language))


    @router.message(AppointmentCreationStates.appointment_datetime, F.text)
    async def get_datetime(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        date_parse_mode = DATA_PARSE_MODE.get(instance)

        if date_parse_mode == "parser":
            if not await datetime_processing(message, state, AppointmentCreationStates.appointment_datetime_confirm, lang=lang):
                return

            data = await state.get_data()
            await message.answer(
                _DID_YOU_MEAN.get(lang, _DID_YOU_MEAN["ru"]).format(value=data.get('appointment_datetime_display')),
                reply_markup=appointment_datetime_confirm_kb(lang=lang),
            )
        elif date_parse_mode == "slots":
            # Admins don't type free text here (they enter choose_day directly),
            # but if they somehow do, re-render the calendar instead of silently
            # swallowing the message.
            await ah.render_calendar_start_from_message(appt_mng, message, state, lang=lang)

    @router.callback_query(AppointmentCreationStates.appointment_datetime_confirm, F.data == "approve_datetime")
    async def confirm_datetime(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        data = await state.get_data()
        parsed_dt = data.get('appointment_datetime_parsed')

        if not parsed_dt:
            await callback_query.answer(
                _DATE_PROCESSING_ERROR.get(lang, _DATE_PROCESSING_ERROR["ru"]),
                show_alert=True
            )
            await state.set_state(AppointmentCreationStates.appointment_datetime)
            return

        db_datetime = format_datetime_for_db(parsed_dt)
        await state.update_data(appointment_datetime=db_datetime)

        await state.set_state(AppointmentCreationStates.purpose)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            _ASK_PURPOSE.get(lang, _ASK_PURPOSE["ru"]),
            reply_markup=back_to_records_kb(lang=lang),
        )

    @router.callback_query(AppointmentCreationStates.appointment_datetime_confirm, F.data == "retry_datetime")
    async def retry_datetime(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        if DATA_PARSE_MODE.get(instance) == "slots":
            await callback_query.answer('')
            await ah.render_calendar_start(appt_mng, callback_query, state, lang=lang)
            return

        await state.set_state(AppointmentCreationStates.appointment_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            datetime_input_prompt(lang),
            reply_markup=back_to_records_kb(lang=lang),
        )

    # Router registration order matters here: this router is included before
    # appointment_browser's (see bot/run.py), and browser's
    # ApptCalendarMonthCB/ApptCalendarDayCB handlers are NOT state-filtered.
    # State-filtering these two handlers to choose_day lets a creation calendar
    # session take priority while its own state is active, and falls through to
    # the browser's calendar handlers otherwise -- keep both the state filter
    # and the router registration order intact.
    @router.callback_query(AppointmentCreationStates.choose_day, ApptCalendarMonthCB.filter())
    async def change_calendar_month(
        callback_query: CallbackQuery, callback_data: ApptCalendarMonthCB, state: FSMContext, current_user: User,
    ):
        year, month = clamp_month_to_range(callback_data.year, callback_data.month)
        await ah.render_calendar_month(callback_query, state, year, month, lang=current_user.language)

    async def render_slot_grid(callback_query: CallbackQuery, state: FSMContext, day_iso: str, lang: str = "ru") -> bool:
        day = date.fromisoformat(day_iso)
        now = get_current_tashkent_datetime()
        data = await state.get_data()
        occupancy = await appt_mng.get_day_slot_occupancy(data["staff_user_id"], day, now)

        if not occupancy:
            return False

        await state.update_data(day_iso=day_iso)
        await state.set_state(AppointmentCreationStates.choose_slot)
        await callback_query.message.edit_text(
            choose_time_for_day_prompt(day.strftime('%d.%m.%Y'), lang),
            reply_markup=appointment_slot_grid_kb(occupancy, cancel_callback_data="admin_book_back_to_day", lang=lang),
        )
        return True

    @router.callback_query(AppointmentCreationStates.choose_day, ApptCalendarDayCB.filter())
    async def pick_calendar_day(
        callback_query: CallbackQuery, callback_data: ApptCalendarDayCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        year, month, day_num = clamp_calendar_date(callback_data.year, callback_data.month, callback_data.day)
        day_iso = date(year, month, day_num).isoformat()

        if not await render_slot_grid(callback_query, state, day_iso, lang):
            await callback_query.answer(_NO_SLOTS_FOR_DAY.get(lang, _NO_SLOTS_FOR_DAY["ru"]), show_alert=True)
            return

        await callback_query.answer()

    @router.callback_query(AppointmentCreationStates.choose_slot, F.data == "admin_book_back_to_day")
    async def back_to_day_selection(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        data = await state.get_data()
        today = get_current_tashkent_datetime().date()
        year = data.get("calendar_year", today.year)
        month = data.get("calendar_month", today.month)
        await ah.render_calendar_month(callback_query, state, year, month, lang=current_user.language)

    @router.callback_query(AppointmentCreationStates.choose_slot, AdminOccupiedSlotCB.filter())
    async def view_occupied_slot(
        callback_query: CallbackQuery, callback_data: AdminOccupiedSlotCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        appointment = await appt_mng.get_appointment_by_id(callback_data.appointment_id)
        if appointment is None:
            await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_appointment_card(appointment, lang),
            reply_markup=occupied_slot_card_kb(lang=lang),
        )

    @router.callback_query(AppointmentCreationStates.choose_slot, F.data == "admin_book_back_to_slots")
    async def back_to_slot_grid(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        data = await state.get_data()
        await render_slot_grid(callback_query, state, data["day_iso"], current_user.language)
        await callback_query.answer()

    @router.callback_query(AppointmentCreationStates.choose_slot, ClientBookSlotCB.filter())
    async def pick_slot(
        callback_query: CallbackQuery, callback_data: ClientBookSlotCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        try:
            datetime.strptime(callback_data.slot, "%H:%M")
        except ValueError:
            await callback_query.answer(_INVALID_TIME.get(lang, _INVALID_TIME["ru"]), show_alert=True)
            return

        data = await state.get_data()
        appointment_datetime = f"{data['day_iso']} {callback_data.slot}"

        await state.update_data(
            slot=callback_data.slot,
            appointment_datetime=appointment_datetime,
            appointment_datetime_display=format_datetime_for_display(
                datetime.strptime(appointment_datetime, "%Y-%m-%d %H:%M")
            ),
        )
        await state.set_state(AppointmentCreationStates.purpose)

        if instance == "zb":
            await callback_query.message.edit_text(
                _ASK_PURPOSE.get(lang, _ASK_PURPOSE["ru"]),
                reply_markup=back_to_records_kb(lang=lang),
            )
        else:
            await callback_query.message.edit_text(
                _ASK_PAIN_OR_PROBLEM.get(lang, _ASK_PAIN_OR_PROBLEM["ru"]),
                reply_markup=back_to_records_kb(lang=lang),
            )
        await callback_query.answer()

    @router.message(AppointmentCreationStates.purpose, F.text)
    async def get_purpose(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        if not await purpose_processing(message, state, AppointmentCreationStates.confirm):
            return
        data = await state.get_data()
        await message.answer(
            build_appointment_confirmation(data, lang),
            reply_markup=appointment_confirm_kb(lang=lang),
        )

    @router.callback_query(AppointmentCreationStates.confirm, F.data == "approve_appointment_create")
    async def finish(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        data = await state.get_data()

        try:
            appointment = await appt_mng.create_appointment(callback_query.from_user.id, data)
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(
                _APPOINTMENT_CREATION_ERROR.get(lang, _APPOINTMENT_CREATION_ERROR["ru"]).format(error=e), show_alert=True,
            )
            return

        notification_text = _APPOINTMENT_CREATED.get(lang, _APPOINTMENT_CREATED["ru"]) + build_appointment_card(appointment, lang)
        if notification_service:
            use_invite_kb = appointment.status == AppointmentStatus.PENDING
            try:
                message_id = await notification_service.notify_client_appointment_with_buttons(
                    appointment, use_invite_kb=use_invite_kb
                )
            except Exception as e:
                logger.warning(f"Failed to notify client about new appointment {appointment.id}: {e}")
                message_id = None

            if message_id:
                await appt_mng.update_notification_message_id(appointment.id, message_id)
                notification_text += _NOTIFICATION_SENT.get(lang, _NOTIFICATION_SENT["ru"])
            else:
                notification_text += _NOTIFICATION_FAILED.get(lang, _NOTIFICATION_FAILED["ru"])

        if scheduler and appointment.status == AppointmentStatus.CONFIRMED:
            notification_text += _REMINDERS_SCHEDULED.get(lang, _REMINDERS_SCHEDULED["ru"])
            notification_text += _AUTO_COMPLETE_SCHEDULED.get(lang, _AUTO_COMPLETE_SCHEDULED["ru"])

        if scheduler:
            await scheduler.resync_appointment_jobs(appointment)

        await callback_query.message.edit_text(
            notification_text,
            reply_markup=back_to_records_kb(lang=lang),
        )
        await appt_mng.update_admin_notification_message_id(appointment.id, callback_query.message.message_id)
        await state.clear()

    return router
