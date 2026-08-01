import logging
from datetime import date, datetime
from bot.handlers.utils.admin_utils.calendar import show_calendar
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config.clinic_instances import DATEPARSER_BY_INSTANCE as DATA_PARSE_MODE
from bot.exceptions.exceptions import BotException, PaginationError
from bot.exceptions.user_exceptions import ValidationError
from bot.handlers.utils.admin_utils import appointment_helpers as ah
from bot.handlers.utils.admin_utils.appointment_browser_helpers import (
    edit_tracked_message,
    remember_tracked_message,
)
from bot.handlers.utils.admin_utils.appointment_calendar_helpers import (
    calendar_grid_back_target,
    clamp_calendar_date,
    clamp_month_to_range,
    format_calendar_date_display,
    format_month_label,
)
from bot.handlers.utils.admin_utils.appointment_helpers import (
    build_appointment_card,
    datetime_processing,
    price_processing,
    purpose_processing,
)
from bot.handlers.utils.admin_utils.confirmations import show_confirmation
from bot.handlers.utils.admin_utils.input_helpers import (
    ask_full_name,
    ask_phone,
    edit_full_name,
    edit_phone,
    full_name_processing,
    phone_processing,
)
from bot.handlers.utils.medical_record_delivery import add_medical_record_document, deliver_medical_record
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import (
    ApptActionCB,
    ApptCalendarDayCB,
    ApptCalendarMonthCB,
    ApptCardCB,
    ApptDoctorFilterCB,
    ApptDoctorFilterEntryCB,
    ApptPageCB,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_kb import (
    appointment_browser_back_to_search_kb,
    appointment_browser_cancel_edit_kb,
    appointment_browser_confirm_name_kb,
    appointment_browser_confirm_phone_kb,
    appointment_browser_search_kb,
    appointment_calendar_kb,
    appointment_card_kb,
    appointment_confirm_new_datetime_kb,
    appointment_confirm_new_price_kb,
    appointment_confirm_new_purpose_kb,
    appointment_delete_confirm_kb,
    appointment_delete_notify_kb,
    appointment_doctor_filter_kb,
    appointment_list_kb,
    appointment_status_menu_kb,
)
from bot.keyboards.admin.record_management_kb.appointment_creation_cb import AdminOccupiedSlotCB
from bot.keyboards.admin.record_management_kb.appointment_slot_kb import appointment_slot_grid_kb, occupied_slot_card_kb
from bot.keyboards.client.booking_cb import ClientBookSlotCB
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_pagination_service import AppointmentPaginationService
from bot.services.utils.date_parser import (
    format_datetime_for_confirmation,
    format_datetime_for_db,
    get_current_tashkent_datetime,
)
from bot.states.admin.record_management.appointment_browser_states import AppointmentBrowserStates
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.role import RoleFilter
from bot.validators.validators import SEARCH_NAME_PATTERN

logger = logging.getLogger(__name__)

_BROWSER_CALENDAR_SEARCH_STATES = StateFilter(
    AppointmentBrowserStates.calendar_month, AppointmentBrowserStates.calendar_day,
)


def create_admin_appointment_browser_router(
    instance: str,
    appointment_repo, user_repo, staff_repo, clinic_repo, appointment_scheduler=None, notification_service=None,
    medical_record_service=None,
):
    router = Router()

    appt_mng = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)
    pagination_service = AppointmentPaginationService(appointment_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    # --- Entry ---

    @router.callback_query(F.data == "browse_appointments")
    async def browse_appointments(callback_query: CallbackQuery, state: FSMContext):
        await state.clear()
        await state.set_state(AppointmentBrowserStates.search_variant)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Выберите способ:",
            reply_markup=appointment_browser_search_kb(),
        )
        await remember_tracked_message(state, callback_query.message)

    # --- Search by full name ---

    @router.callback_query(F.data == "appt_search_name")
    async def search_by_name(callback_query: CallbackQuery, state: FSMContext):
        await ask_full_name(
            callback_query, state,
            next_state=AppointmentBrowserStates.search_name,
            reply_markup=appointment_browser_back_to_search_kb(),
        )

    @router.message(AppointmentBrowserStates.search_name, F.text)
    async def process_search_name(message: Message, state: FSMContext):
        if not await full_name_processing(
            message, state,
            next_state=AppointmentBrowserStates.confirm_search,
            re_pattern=SEARCH_NAME_PATTERN,
        ):
            return
        await show_confirmation(message, state, reply_markup=appointment_browser_confirm_name_kb())

    @router.callback_query(AppointmentBrowserStates.confirm_search, F.data == "appt_edit_search_name")
    async def edit_search_name(callback_query: CallbackQuery, state: FSMContext):
        await edit_full_name(
            callback_query, state,
            edit_state=AppointmentBrowserStates.edit_search_full_name,
            reply_markup=appointment_browser_back_to_search_kb(),
        )

    @router.message(AppointmentBrowserStates.edit_search_full_name, F.text)
    async def process_edit_search_name(message: Message, state: FSMContext):
        if not await full_name_processing(
            message, state,
            next_state=AppointmentBrowserStates.confirm_search,
            re_pattern=SEARCH_NAME_PATTERN,
        ):
            return
        await show_confirmation(message, state, reply_markup=appointment_browser_confirm_name_kb())

    # --- Search by phone ---

    @router.callback_query(F.data == "appt_search_phone")
    async def search_by_phone(callback_query: CallbackQuery, state: FSMContext):
        await ask_phone(
            callback_query, state,
            AppointmentBrowserStates.search_phone,
            reply_markup=appointment_browser_back_to_search_kb(),
        )

    @router.message(AppointmentBrowserStates.search_phone, F.text)
    async def process_search_phone(message: Message, state: FSMContext):
        if not await phone_processing(message, state, final_state=AppointmentBrowserStates.confirm_search):
            return
        await show_confirmation(message, state, reply_markup=appointment_browser_confirm_phone_kb())

    @router.callback_query(AppointmentBrowserStates.confirm_search, F.data == "appt_edit_search_phone")
    async def edit_search_phone(callback_query: CallbackQuery, state: FSMContext):
        await edit_phone(
            callback_query, state,
            edit_state=AppointmentBrowserStates.edit_search_phone,
            reply_markup=appointment_browser_back_to_search_kb(),
        )

    @router.message(AppointmentBrowserStates.edit_search_phone, F.text)
    async def process_edit_search_phone(message: Message, state: FSMContext):
        if not await phone_processing(message, state, final_state=AppointmentBrowserStates.confirm_search):
            return
        await show_confirmation(message, state, reply_markup=appointment_browser_confirm_phone_kb())

    # --- Show all appointments (skips search entirely) ---

    @router.callback_query(F.data == "appt_search_all")
    async def search_all(callback_query: CallbackQuery, state: FSMContext):
        await state.clear()
        clinic_id, doctor_id = await appt_mng.resolve_admin_appointment_filter(callback_query.from_user.id)

        if await maybe_prompt_doctor_filter(callback_query, state, mode="list", page=1, tab="confirmed"):
            return

        await render_list(
            callback_query, state, mode="list", page=1, tab="confirmed", clinic_id=clinic_id, doctor_id=doctor_id,
        )

    # --- Calendar search ---

    @router.callback_query(F.data == "appt_search_calendar")
    async def open_calendar_callback(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        if await maybe_prompt_doctor_filter(callback, state, mode="calendar_entry", page=1, tab="confirmed"):
            return
        await show_calendar(callback, state)

    @router.message(F.text.in_({"/calendar", "📆 Календарь"}))
    async def open_calendar_message(message: Message, state: FSMContext):
        await state.clear()
        if await maybe_prompt_doctor_filter(message, state, mode="calendar_entry", page=1, tab="confirmed"):
            return
        await show_calendar(message, state)

    # These two handlers back the browser's own read-only calendar search,
    # so they're scoped to _BROWSER_CALENDAR_SEARCH_STATES (calendar_month/
    # calendar_day) rather than left unfiltered by state -- that keeps them
    # from shadowing the edit-datetime calendar/slot picker below (registered
    # later in this file, in AppointmentBrowserStates.edit_choose_day/
    # edit_choose_slot) and makes any future new AppointmentBrowserStates
    # state default to NOT matching these two handlers.
    @router.callback_query(_BROWSER_CALENDAR_SEARCH_STATES, ApptCalendarMonthCB.filter())
    async def change_calendar_month(
        callback_query: CallbackQuery, callback_data: ApptCalendarMonthCB, state: FSMContext,
    ):
        year, month = clamp_month_to_range(callback_data.year, callback_data.month)

        data = await state.update_data(calendar_year=year, calendar_month=month)
        await state.set_state(AppointmentBrowserStates.calendar_month)
        await callback_query.answer('')

        back_callback_data, back_label = calendar_grid_back_target(data)

        try:
            await callback_query.message.edit_text(
                f"📅 {format_month_label(year, month)}",
                reply_markup=appointment_calendar_kb(
                    year, month, back_callback_data=back_callback_data, back_label=back_label,
                ),
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise

        await remember_tracked_message(state, callback_query.message)

    @router.callback_query(_BROWSER_CALENDAR_SEARCH_STATES, ApptCalendarDayCB.filter())
    async def pick_calendar_day(
        callback_query: CallbackQuery, callback_data: ApptCalendarDayCB, state: FSMContext,
    ):
        year, month, day = clamp_calendar_date(callback_data.year, callback_data.month, callback_data.day)
        calendar_date = f"{year:04d}-{month:02d}-{day:02d}"

        await state.update_data(
            calendar_date=calendar_date, calendar_year=year, calendar_month=month,
        )
        await state.set_state(AppointmentBrowserStates.calendar_day)

        data = await state.get_data()
        if "calendar_doctor_filter_id" not in data:
            prompted = await maybe_prompt_doctor_filter(
                callback_query, state, mode="calendar", page=1, tab="confirmed",
                back_callback_data=ApptCalendarMonthCB(year=year, month=month).pack(),
                back_label="⬅️ К календарю",
            )
            if prompted:
                return

        clinic_id, doctor_id = await resolve_filtered_doctor_id(callback_query.from_user.id, state, mode="calendar")
        await render_list(
            callback_query, state, mode="calendar", page=1, tab="confirmed", clinic_id=clinic_id, doctor_id=doctor_id,
        )

    # --- Resolve the search query and show results ---

    @router.callback_query(AppointmentBrowserStates.confirm_search, F.data == "appt_approve_search")
    async def approve_search(callback_query: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        clinic_id, doctor_id = await appt_mng.resolve_admin_appointment_filter(callback_query.from_user.id)

        if data.get("phone"):
            client = await appt_mng.find_client_by_phone(data["phone"], clinic_id)
            if client is None:
                await callback_query.answer("Клиент не был найден.", show_alert=True)
                return

            await state.update_data(search_data={"client_id": client.ID})
            if await maybe_prompt_doctor_filter(callback_query, state, mode="phone", page=1, tab="confirmed"):
                return

            await render_list(
                callback_query, state, mode="phone", page=1, tab="confirmed",
                clinic_id=clinic_id, doctor_id=doctor_id,
            )
            return

        if data.get("full_name"):
            await state.update_data(search_data={"full_name": data["full_name"]})
            if await maybe_prompt_doctor_filter(callback_query, state, mode="search", page=1, tab="confirmed"):
                return

            await render_list(
                callback_query, state, mode="search", page=1, tab="confirmed",
                clinic_id=clinic_id, doctor_id=doctor_id,
            )
            return

        await callback_query.answer("Укажите телефон или ФИ для поиска.", show_alert=True)

    # --- Pagination ---

    @router.callback_query(ApptPageCB.filter())
    async def paginate(callback_query: CallbackQuery, callback_data: ApptPageCB, state: FSMContext):
        clinic_id, doctor_id = await resolve_filtered_doctor_id(
            callback_query.from_user.id, state, callback_data.mode
        )
        await render_list(
            callback_query, state, mode=callback_data.mode, page=callback_data.page, tab=callback_data.tab,
            clinic_id=clinic_id, doctor_id=doctor_id,
        )

    # --- Open an appointment's card ---

    @router.callback_query(ApptCardCB.filter())
    async def open_card(callback_query: CallbackQuery, callback_data: ApptCardCB, state: FSMContext):
        await render_card(
            callback_query, state,
            appointment_id=callback_data.appointment_id, mode=callback_data.mode, page=callback_data.page,
            tab=callback_data.tab, post_appt=callback_data.post_appt,
        )

    # --- Card actions: status ---

    @router.callback_query(ApptActionCB.filter(F.action == "set_status"))
    async def set_status(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        try:
            new_status = AppointmentStatus(callback_data.value)
        except ValueError:
            await callback_query.answer("Некорректный статус.", show_alert=True)
            return

        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        try:
            appointment = await appt_mng.update_status(owned_appointment, new_status)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        if appointment_scheduler:
            # Forcing status via this handler now also (re)schedules reminders when
            # confirmed and no longer schedules a completion-followup job when
            # forced to PENDING -- both intentional alignment with the
            # system-wide resync_appointment_jobs rules, not regressions.
            await appointment_scheduler.resync_appointment_jobs(appointment)

        if notification_service and new_status == AppointmentStatus.CANCELLED and not callback_data.post_appt:
            try:
                await notification_service.notify_client_appointment_cancelled_by_admin(appointment)
            except Exception as e:
                logger.warning(
                    f"Failed to notify client about cancellation for appointment {callback_data.appointment_id}: {e}"
                )

        await callback_query.answer("Статус обновлён")
        await callback_query.message.edit_text(
            build_appointment_card(appointment),
            reply_markup=appointment_card_kb(
                callback_data.appointment_id, callback_data.mode, callback_data.page, status=appointment.status,
            ),
        )
        await remember_tracked_message(state, callback_query.message)

    @router.callback_query(ApptActionCB.filter(F.action == "status_menu"))
    async def open_status_menu(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        appointment = await appt_mng.get_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id)
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_appointment_card(appointment),
            reply_markup=appointment_status_menu_kb(
                callback_data.appointment_id, callback_data.mode, callback_data.page, tab="", status=appointment.status,
            ),
        )
        await remember_tracked_message(state, callback_query.message)

    @router.callback_query(ApptActionCB.filter(F.action == "select_status"))
    async def select_status(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        try:
            selected_status = AppointmentStatus(callback_data.value)
        except ValueError:
            await callback_query.answer("Некорректный статус.", show_alert=True)
            return

        appointment = await appt_mng.get_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id)
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_appointment_card(appointment),
            reply_markup=appointment_card_kb(
                callback_data.appointment_id, callback_data.mode, callback_data.page, status=appointment.status,
                post_appt=True, selected_status=selected_status,
            ),
        )
        await remember_tracked_message(state, callback_query.message)

    # --- Card actions: delete ---

    @router.callback_query(ApptActionCB.filter(F.action == "delete"))
    async def start_delete(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        appointment = await appt_mng.get_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id)
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        await state.set_state(AppointmentBrowserStates.confirm_delete)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            f"⚠️ Удалить запись №{appointment.id} безвозвратно?",
            reply_markup=appointment_delete_confirm_kb(
                callback_data.appointment_id, callback_data.mode, callback_data.page,
            ),
        )

    @router.callback_query(ApptActionCB.filter(F.action == "cancel_delete"))
    async def cancel_delete(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        await render_card(
            callback_query, state,
            appointment_id=callback_data.appointment_id, mode=callback_data.mode, page=callback_data.page,
        )

    @router.callback_query(ApptActionCB.filter(F.action == "confirm_delete"))
    async def confirm_delete(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        appointment = await appt_mng.get_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id)
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Уведомить клиента об удалении записи?",
            reply_markup=appointment_delete_notify_kb(
                callback_data.appointment_id, callback_data.mode, callback_data.page,
            ),
        )

    @router.callback_query(ApptActionCB.filter(F.action == "confirm_delete_notify"))
    async def confirm_delete_notify(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        await finish_delete(callback_query, callback_data, state, notify=True)

    @router.callback_query(ApptActionCB.filter(F.action == "confirm_delete_silent"))
    async def confirm_delete_silent(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        await finish_delete(callback_query, callback_data, state, notify=False)

    async def finish_delete(
        callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext, *, notify: bool,
    ) -> None:
        appointment = await appt_mng.get_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id)
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        try:
            await appt_mng.delete_appointment(appointment)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.cancel_all_jobs(callback_data.appointment_id)

        if notify and notification_service and appointment:
            try:
                await notification_service.notify_client_appointment_cancelled_by_admin(appointment)
            except Exception as e:
                logger.warning(
                    f"Failed to notify client about deletion for appointment {callback_data.appointment_id}: {e}"
                )

        clinic_id, doctor_id = await resolve_filtered_doctor_id(
            callback_query.from_user.id, state, callback_data.mode
        )
        await render_list(
            callback_query, state,
            mode=callback_data.mode, page=callback_data.page, prefix="✅ Запись удалена.\n\n",
            clinic_id=clinic_id, doctor_id=doctor_id,
        )

    @router.callback_query(ApptActionCB.filter(F.action == "cancel_edit"))
    async def cancel_edit(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        await render_card(
            callback_query, state,
            appointment_id=callback_data.appointment_id, mode=callback_data.mode, page=callback_data.page,
            post_appt=callback_data.post_appt,
        )

    # --- Collect and confirm new datetime ---

    def edit_datetime_back_target(appointment_id: int, mode: str, page: int) -> tuple[str, str]:
        return (
            ApptActionCB(action="cancel_edit", appointment_id=appointment_id, mode=mode, page=page).pack(),
            "❌ Отменить",
        )

    async def enter_edit_datetime_calendar(
        callback_query: CallbackQuery, state: FSMContext, appointment_id: int, mode: str, page: int,
    ) -> None:
        await callback_query.answer('')
        today = get_current_tashkent_datetime().date()
        year, month = clamp_month_to_range(today.year, today.month)
        back_callback_data, back_label = edit_datetime_back_target(appointment_id, mode, page)
        await ah.render_calendar_month(
            callback_query, state, year, month,
            choose_day_state=AppointmentBrowserStates.edit_choose_day,
            back_callback_data=back_callback_data, back_label=back_label,
        )

    @router.callback_query(ApptActionCB.filter(F.action == "edit_datetime"))
    async def start_edit_datetime(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        appointment = await appt_mng.get_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id)
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        await state.update_data(
            appointment_id=callback_data.appointment_id, mode=callback_data.mode, page=callback_data.page,
        )

        if DATA_PARSE_MODE.get(instance) == "slots":
            await state.update_data(staff_user_id=appointment.doctor_id, old_datetime=appointment.datetime)
            await enter_edit_datetime_calendar(
                callback_query, state, callback_data.appointment_id, callback_data.mode, callback_data.page,
            )
            return

        await state.set_state(AppointmentBrowserStates.new_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите новую дату и время (например: завтра в 15:00):",
            reply_markup=appointment_browser_cancel_edit_kb(
                callback_data.appointment_id, callback_data.mode, callback_data.page,
            ),
        )

    @router.message(AppointmentBrowserStates.new_datetime, F.text)
    async def process_new_datetime(message: Message, state: FSMContext):
        if not await datetime_processing(message, state, AppointmentBrowserStates.confirm_new_datetime):
            return

        data = await state.get_data()
        await message.delete()
        await edit_tracked_message(
            message.bot, state,
            text=f"Новая дата и время: {data.get('appointment_datetime_display')}",
            reply_markup=appointment_confirm_new_datetime_kb(data["appointment_id"], data["mode"], data["page"]),
        )

    # This calendar/slot picker mirrors appointment_creation.py's Phase C
    # implementation but is scoped to AppointmentBrowserStates.edit_choose_day/
    # edit_choose_slot -- distinct from the browser's own read-only
    # calendar_month/calendar_day search states above. Scoping that read-only
    # calendar's handlers to _BROWSER_CALENDAR_SEARCH_STATES keeps them from
    # shadowing these while this flow's state is active.
    @router.callback_query(AppointmentBrowserStates.edit_choose_day, ApptCalendarMonthCB.filter())
    async def change_edit_datetime_calendar_month(
        callback_query: CallbackQuery, callback_data: ApptCalendarMonthCB, state: FSMContext,
    ):
        year, month = clamp_month_to_range(callback_data.year, callback_data.month)
        data = await state.get_data()
        back_callback_data, back_label = edit_datetime_back_target(data["appointment_id"], data["mode"], data["page"])
        await ah.render_calendar_month(
            callback_query, state, year, month,
            choose_day_state=AppointmentBrowserStates.edit_choose_day,
            back_callback_data=back_callback_data, back_label=back_label,
        )

    async def render_edit_datetime_slot_grid(callback_query: CallbackQuery, state: FSMContext, day_iso: str) -> bool:
        day = date.fromisoformat(day_iso)
        now = get_current_tashkent_datetime()
        data = await state.get_data()
        occupancy = await appt_mng.get_day_slot_occupancy(
            data["staff_user_id"], day, now, exclude_appointment_id=data["appointment_id"],
        )

        if not occupancy:
            return False

        await state.update_data(day_iso=day_iso)
        await state.set_state(AppointmentBrowserStates.edit_choose_slot)
        await callback_query.message.edit_text(
            f"Выберите время на {day.strftime('%d.%m.%Y')}:",
            reply_markup=appointment_slot_grid_kb(occupancy, cancel_callback_data="admin_book_back_to_day"),
        )
        return True

    @router.callback_query(AppointmentBrowserStates.edit_choose_day, ApptCalendarDayCB.filter())
    async def pick_edit_datetime_calendar_day(
        callback_query: CallbackQuery, callback_data: ApptCalendarDayCB, state: FSMContext,
    ):
        year, month, day_num = clamp_calendar_date(callback_data.year, callback_data.month, callback_data.day)
        day_iso = date(year, month, day_num).isoformat()

        if not await render_edit_datetime_slot_grid(callback_query, state, day_iso):
            await callback_query.answer("На этот день нет доступных слотов.", show_alert=True)
            return

        await callback_query.answer()

    @router.callback_query(AppointmentBrowserStates.edit_choose_slot, F.data == "admin_book_back_to_day")
    async def back_to_edit_datetime_day_selection(callback_query: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        today = get_current_tashkent_datetime().date()
        year = data.get("calendar_year", today.year)
        month = data.get("calendar_month", today.month)
        back_callback_data, back_label = edit_datetime_back_target(data["appointment_id"], data["mode"], data["page"])
        await ah.render_calendar_month(
            callback_query, state, year, month,
            choose_day_state=AppointmentBrowserStates.edit_choose_day,
            back_callback_data=back_callback_data, back_label=back_label,
        )

    @router.callback_query(AppointmentBrowserStates.edit_choose_slot, AdminOccupiedSlotCB.filter())
    async def view_edit_datetime_occupied_slot(
        callback_query: CallbackQuery, callback_data: AdminOccupiedSlotCB, state: FSMContext,
    ):
        appointment = await appt_mng.get_appointment_by_id(callback_data.appointment_id)
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_appointment_card(appointment),
            reply_markup=occupied_slot_card_kb(),
        )

    @router.callback_query(AppointmentBrowserStates.edit_choose_slot, F.data == "admin_book_back_to_slots")
    async def back_to_edit_datetime_slot_grid(callback_query: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        await render_edit_datetime_slot_grid(callback_query, state, data["day_iso"])
        await callback_query.answer()

    @router.callback_query(AppointmentBrowserStates.edit_choose_slot, ClientBookSlotCB.filter())
    async def pick_edit_datetime_slot(callback_query: CallbackQuery, callback_data: ClientBookSlotCB, state: FSMContext):
        try:
            datetime.strptime(callback_data.slot, "%H:%M")
        except ValueError:
            await callback_query.answer("Некорректное время, попробуйте ещё раз.", show_alert=True)
            return

        data = await state.get_data()
        appointment_datetime = f"{data['day_iso']} {callback_data.slot}"
        parsed_dt = datetime.strptime(appointment_datetime, "%Y-%m-%d %H:%M")
        new_display = format_datetime_for_confirmation(parsed_dt)

        await state.update_data(appointment_datetime_parsed=parsed_dt, appointment_datetime_display=new_display)
        await state.set_state(AppointmentBrowserStates.confirm_new_datetime)

        old_display = format_datetime_for_confirmation(datetime.fromisoformat(data["old_datetime"]))
        await callback_query.message.edit_text(
            f"Новая дата и время: {old_display} → {new_display}",
            reply_markup=appointment_confirm_new_datetime_kb(data["appointment_id"], data["mode"], data["page"]),
        )
        await callback_query.answer()

    @router.callback_query(ApptActionCB.filter(F.action == "retry_new_datetime"))
    async def retry_new_datetime(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        if DATA_PARSE_MODE.get(instance) == "slots":
            await enter_edit_datetime_calendar(
                callback_query, state, callback_data.appointment_id, callback_data.mode, callback_data.page,
            )
            return

        await state.set_state(AppointmentBrowserStates.new_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите новую дату и время (например: завтра в 15:00):",
            reply_markup=appointment_browser_cancel_edit_kb(
                callback_data.appointment_id, callback_data.mode, callback_data.page,
            ),
        )

    @router.callback_query(ApptActionCB.filter(F.action == "approve_new_datetime"))
    async def approve_new_datetime(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        data = await state.get_data()
        parsed_dt = data.get("appointment_datetime_parsed")

        if not parsed_dt:
            await callback_query.answer(
                "Ошибка: не удалось обработать дату. Попробуйте снова.", show_alert=True,
            )
            return

        db_datetime = format_datetime_for_db(parsed_dt)

        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        try:
            appointment = await appt_mng.propose_new_datetime(
                callback_data.appointment_id, callback_query.from_user.id, db_datetime, kind="reschedule",
            )
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка обновления записи: {e}", show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

        old_display = format_datetime_for_confirmation(datetime.fromisoformat(owned_appointment.datetime))

        if appointment.status == AppointmentStatus.CONFIRMED:
            await callback_query.answer("Время записи изменено")
            await callback_query.message.edit_text(
                f"✅ Время записи изменено: {old_display} → {data.get('appointment_datetime_display')}"
            )
            await state.clear()
            return

        if notification_service:
            try:
                message_id = await notification_service.notify_client_appointment_with_buttons(
                    appointment, rescheduled=True,
                )
                if message_id:
                    await appt_mng.update_notification_message_id(appointment.id, message_id)
            except Exception as e:
                logger.warning(
                    f"Failed to notify client about new pending time for appointment {callback_data.appointment_id}: {e}"
                )

        await callback_query.answer("Время записи изменено, клиенту отправлено уведомление")
        await callback_query.message.edit_text(
            f"🔁 Время записи изменено: {old_display} → {data.get('appointment_datetime_display')}\n"
            "Ожидаем подтверждения клиента."
        )
        await state.clear()

    # --- Collect and confirm new purpose ---

    @router.callback_query(ApptActionCB.filter(F.action == "edit_purpose"))
    async def start_edit_purpose(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        appointment = await appt_mng.get_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id)
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        await state.update_data(
            appointment_id=callback_data.appointment_id, mode=callback_data.mode, page=callback_data.page,
            post_appt=callback_data.post_appt,
        )
        await state.set_state(AppointmentBrowserStates.new_purpose)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите новое описание услуги:",
            reply_markup=appointment_browser_cancel_edit_kb(
                callback_data.appointment_id, callback_data.mode, callback_data.page,
                post_appt=callback_data.post_appt,
            ),
        )

    @router.message(AppointmentBrowserStates.new_purpose, F.text)
    async def process_new_purpose(message: Message, state: FSMContext):
        if not await purpose_processing(message, state, AppointmentBrowserStates.confirm_new_purpose):
            return

        data = await state.get_data()
        await message.delete()
        await edit_tracked_message(
            message.bot, state,
            text=f"Новая услуга: {data['purpose']}",
            reply_markup=appointment_confirm_new_purpose_kb(
                data["appointment_id"], data["mode"], data["page"], post_appt=data.get("post_appt", False),
            ),
        )

    @router.callback_query(ApptActionCB.filter(F.action == "retry_new_purpose"))
    async def retry_new_purpose(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        await state.set_state(AppointmentBrowserStates.new_purpose)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите новое описание услуги:",
            reply_markup=appointment_browser_cancel_edit_kb(
                callback_data.appointment_id, callback_data.mode, callback_data.page,
                post_appt=callback_data.post_appt,
            ),
        )

    @router.callback_query(ApptActionCB.filter(F.action == "approve_new_purpose"))
    async def approve_new_purpose(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        data = await state.get_data()

        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        try:
            appointment = await appt_mng.update_purpose(owned_appointment, data["purpose"])
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка обновления записи: {e}", show_alert=True)
            return

        await notify_appointment_changed(appointment, callback_data.appointment_id)

        await render_card(
            callback_query, state,
            appointment_id=callback_data.appointment_id, mode=callback_data.mode, page=callback_data.page,
            post_appt=callback_data.post_appt,
        )

    # --- Collect and confirm new price ---

    @router.callback_query(ApptActionCB.filter(F.action == "edit_price"))
    async def start_edit_price(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        appointment = await appt_mng.get_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id)
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        await state.update_data(
            appointment_id=callback_data.appointment_id, mode=callback_data.mode, page=callback_data.page,
            post_appt=callback_data.post_appt,
        )
        await state.set_state(AppointmentBrowserStates.new_price)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите цену приёма:",
            reply_markup=appointment_browser_cancel_edit_kb(
                callback_data.appointment_id, callback_data.mode, callback_data.page,
                post_appt=callback_data.post_appt,
            ),
        )

    @router.message(AppointmentBrowserStates.new_price, F.text)
    async def process_new_price(message: Message, state: FSMContext):
        if not await price_processing(message, state, AppointmentBrowserStates.confirm_new_price):
            return

        data = await state.get_data()
        await message.delete()
        await edit_tracked_message(
            message.bot, state,
            text=f"Новая цена: {data['price']}",
            reply_markup=appointment_confirm_new_price_kb(
                data["appointment_id"], data["mode"], data["page"], post_appt=data.get("post_appt", False),
            ),
        )

    @router.callback_query(ApptActionCB.filter(F.action == "retry_new_price"))
    async def retry_new_price(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        await state.set_state(AppointmentBrowserStates.new_price)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите цену приёма:",
            reply_markup=appointment_browser_cancel_edit_kb(
                callback_data.appointment_id, callback_data.mode, callback_data.page,
                post_appt=callback_data.post_appt,
            ),
        )

    @router.callback_query(ApptActionCB.filter(F.action == "approve_new_price"))
    async def approve_new_price(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        data = await state.get_data()

        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        try:
            appointment = await appt_mng.update_price(owned_appointment, data["price"])
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка обновления записи: {e}", show_alert=True)
            return

        await render_card(
            callback_query, state,
            appointment_id=callback_data.appointment_id, mode=callback_data.mode, page=callback_data.page,
            post_appt=callback_data.post_appt,
        )

    # --- Finish appointment (post-appointment window) ---

    @router.callback_query(ApptActionCB.filter(F.action == "finish_appointment"))
    async def finish_appointment(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        try:
            selected_status = AppointmentStatus(callback_data.value) if callback_data.value else AppointmentStatus.COMPLETED
        except ValueError:
            selected_status = AppointmentStatus.COMPLETED

        try:
            appointment = await appt_mng.update_status(owned_appointment, selected_status)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

        await callback_query.answer("Статус обновлён")
        await callback_query.message.edit_text(
            build_appointment_card(appointment),
            reply_markup=appointment_card_kb(
                callback_data.appointment_id, callback_data.mode, callback_data.page, status=appointment.status,
            ),
        )
        await remember_tracked_message(state, callback_query.message)

    # --- Medical record retrieval ---

    if medical_record_service:
        @router.callback_query(ApptActionCB.filter(F.action == "get_medical_record"))
        async def get_medical_record(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
            appointment = await appt_mng.get_appointment_for_admin(
                callback_data.appointment_id, callback_query.from_user.id
            )
            if appointment is None:
                await callback_query.answer("Запись не найдена.", show_alert=True)
                return

            await deliver_medical_record(callback_query, medical_record_service, callback_data.appointment_id)

        @router.callback_query(ApptActionCB.filter(F.action == "add_medical_record"))
        async def add_medical_record(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
            appointment = await appt_mng.get_appointment_for_admin(
                callback_data.appointment_id, callback_query.from_user.id
            )
            if appointment is None:
                await callback_query.answer("Запись не найдена.", show_alert=True)
                return

            await add_medical_record_document(
                callback_query, medical_record_service, callback_data.appointment_id, appointment.purpose,
            )

    @router.callback_query(F.data == "noop")
    async def noop_button(callback_query: CallbackQuery):
        await callback_query.answer()

    # --- Shared renderers ---

    DOCTOR_FILTER_STATE_KEYS = {
        "list": "doctor_filter_id",
        "search": "doctor_filter_id",
        "phone": "doctor_filter_id",
        "calendar": "calendar_doctor_filter_id",
        "calendar_entry": "calendar_doctor_filter_id",
    }

    def list_doctor_filter_back_target(state_data: dict, mode: str) -> tuple[str, str]:
        if DOCTOR_FILTER_STATE_KEYS.get(mode, "doctor_filter_id") in state_data:
            return ApptDoctorFilterEntryCB(mode=mode).pack(), "⬅️ К выбору врача"
        return "browse_appointments", "⬅️ К меню поиска"

    async def notify_appointment_changed(appointment, appointment_id: int) -> None:
        if not notification_service:
            return

        try:
            await notification_service.notify_client_appointment_changed(appointment)
        except Exception as e:
            logger.warning(
                f"Failed to notify client about changes for appointment {appointment_id}: {e}"
            )

    async def maybe_prompt_doctor_filter(
        event: CallbackQuery | Message, state: FSMContext, *, mode: str, page: int, tab: str,
        back_callback_data: str = "browse_appointments", back_label: str = "⬅️ К меню поиска",
    ) -> bool:
        doctors = await appt_mng.list_clinic_doctors_for_filter(event.from_user.id)
        if not doctors:
            return False

        await state.update_data(pending_render={"mode": mode, "page": page, "tab": tab})
        await state.set_state(AppointmentBrowserStates.pick_doctor_filter)

        markup = appointment_doctor_filter_kb(
            doctors, back_callback_data=back_callback_data, back_label=back_label,
        )

        if isinstance(event, CallbackQuery):
            await event.answer('')
            await event.message.edit_text("Выберите врача для фильтрации:", reply_markup=markup)
            await remember_tracked_message(state, event.message)
        else:
            sent = await event.answer("Выберите врача для фильтрации:", reply_markup=markup)
            await remember_tracked_message(state, sent)

        return True

    async def resolve_filtered_doctor_id(telegram_id: int, state: FSMContext, mode: str) -> tuple[int, int | None]:
        clinic_id, doctor_id = await appt_mng.resolve_admin_appointment_filter(telegram_id)
        state_key = DOCTOR_FILTER_STATE_KEYS.get(mode)
        if state_key:
            data = await state.get_data()
            if state_key in data:
                doctor_id = data[state_key]
        return clinic_id, doctor_id

    @router.callback_query(ApptDoctorFilterEntryCB.filter())
    async def reenter_doctor_filter(
        callback_query: CallbackQuery, callback_data: ApptDoctorFilterEntryCB, state: FSMContext,
    ):
        await maybe_prompt_doctor_filter(callback_query, state, mode=callback_data.mode, page=1, tab="confirmed")

    @router.callback_query(AppointmentBrowserStates.pick_doctor_filter, ApptDoctorFilterCB.filter())
    async def apply_doctor_filter(
        callback_query: CallbackQuery, callback_data: ApptDoctorFilterCB, state: FSMContext,
    ):
        doctor_id = callback_data.doctor_id or None

        data = await state.get_data()
        pending = data.get("pending_render", {})
        mode = pending.get("mode", "list")
        state_key = DOCTOR_FILTER_STATE_KEYS.get(mode, "doctor_filter_id")
        await state.update_data(**{state_key: doctor_id})

        if mode == "calendar_entry":
            await show_calendar(callback_query, state)
            return

        clinic_id, doctor_id = await resolve_filtered_doctor_id(callback_query.from_user.id, state, mode)

        if mode in ("search", "phone"):
            await state.set_state(AppointmentBrowserStates.confirm_search)
        elif mode == "calendar":
            await state.set_state(AppointmentBrowserStates.calendar_day)
        else:
            await state.set_state(None)

        await render_list(
            callback_query, state,
            mode=mode, page=pending.get("page", 1), tab=pending.get("tab", "confirmed"),
            clinic_id=clinic_id, doctor_id=doctor_id,
        )

    async def render_list(
        callback_query: CallbackQuery, state: FSMContext, *, mode: str, page: int, clinic_id: int,
        doctor_id: int | None = None, tab: str = "", prefix: str = "",
    ) -> None:
        try:
            tab = tab or "confirmed"
            back_callback_data = "browse_appointments"
            back_label = "⬅️ К меню поиска"

            if mode == "list":
                data = await state.get_data()
                result = await pagination_service.paginate_all_appointments_by_tab(
                    tab, page, clinic_id, doctor_id
                )
                title = "📒 Все записи"
                back_callback_data, back_label = list_doctor_filter_back_target(data, mode)
            elif mode == "calendar":
                data = await state.get_data()
                calendar_date = data.get("calendar_date")
                calendar_year = data.get("calendar_year")
                calendar_month = data.get("calendar_month")

                result = await pagination_service.paginate_appointments_by_date_and_tab(
                    calendar_date, tab, page, clinic_id, doctor_id
                )
                title = f"📅 Записи за {format_calendar_date_display(calendar_date)}"
                back_callback_data = ApptCalendarMonthCB(year=calendar_year, month=calendar_month).pack()
                back_label = "⬅️ К календарю"
            else:
                data = await state.get_data()
                search_data = None
                if mode in ("search", "phone"):
                    search_data = data.get("search_data") or {}

                result = await pagination_service.paginate_appointments(
                    mode, page, clinic_id, doctor_id, search_data, tab
                )
                titles = {
                    "search": "🔍 Результаты поиска",
                    "phone": "📞 Записи клиента",
                }
                title = titles.get(mode, "📒 Записи")
                back_callback_data, back_label = list_doctor_filter_back_target(data, mode)

            text = f"{prefix}{title} ({result.current_page} из {result.total_pages}) | Всего: {result.total_count}"

            await callback_query.message.edit_text(
                text,
                reply_markup=appointment_list_kb(
                    result.items, mode, result.current_page, result.total_pages, tab,
                    back_callback_data=back_callback_data, back_label=back_label,
                ),
            )
            await callback_query.answer()
            await remember_tracked_message(state, callback_query.message)

        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback_query.answer()
            else:
                logger.warning(f"TelegramBadRequest in render_list: {e}")
                await callback_query.answer("Ошибка редактирования сообщения", show_alert=False)
        except PaginationError as e:
            logger.warning(f"Pagination error in render_list: {e}")
            await callback_query.answer(str(e), show_alert=True)
        except Exception as e:
            logger.exception(f"Unexpected error in render_list: {e}")
            await callback_query.answer("Произошла непредвиденная ошибка", show_alert=True)

    async def render_card(
        callback_query: CallbackQuery, state: FSMContext, *, appointment_id: int, mode: str, page: int, tab: str = "",
        post_appt: bool = False,
    ) -> None:
        appointment = await appt_mng.get_appointment_for_admin(appointment_id, callback_query.from_user.id)
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_appointment_card(appointment),
            reply_markup=appointment_card_kb(
                appointment_id, mode, page, status=appointment.status, tab=tab, post_appt=post_appt,
            ),
        )
        await remember_tracked_message(state, callback_query.message)

    return router
