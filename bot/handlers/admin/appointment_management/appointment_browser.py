import logging
from datetime import datetime
from bot.handlers.utils.admin_utils.calendar import show_calendar
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.exceptions import BotException, PaginationError
from bot.exceptions.user_exceptions import ValidationError
from bot.handlers.utils.admin_utils.appointment_browser_helpers import (
    edit_tracked_message,
    remember_tracked_message,
)
from bot.handlers.utils.admin_utils.appointment_calendar_helpers import (
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
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import (
    ApptActionCB,
    ApptCalendarDayCB,
    ApptCalendarMonthCB,
    ApptCardCB,
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
    appointment_list_kb,
)
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_pagination_service import AppointmentPaginationService
from bot.services.utils.date_parser import (
    format_datetime_for_db,
    format_datetime_for_display,
)
from bot.states.admin.record_management.appointment_browser_states import AppointmentBrowserStates
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.role import RoleFilter
from bot.validators.validators import SEARCH_NAME_PATTERN

logger = logging.getLogger(__name__)


def create_admin_appointment_browser_router(
    appointment_repo, user_repo, staff_repo, clinic_repo, appointment_scheduler=None, notification_service=None
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
        await render_list(
            callback_query, state, mode="list", page=1, tab="confirmed", clinic_id=clinic_id, doctor_id=doctor_id,
        )

    # --- Calendar search ---

    @router.callback_query(F.data == "appt_search_calendar")
    async def open_calendar_callback(callback: CallbackQuery, state: FSMContext):
        await show_calendar(callback, state)

    @router.message(F.text == "📆 Календарь")
    async def open_calendar_message(message: Message, state: FSMContext):
        await show_calendar(message, state)

    @router.callback_query(ApptCalendarMonthCB.filter())
    async def change_calendar_month(
        callback_query: CallbackQuery, callback_data: ApptCalendarMonthCB, state: FSMContext,
    ):
        year, month = clamp_month_to_range(callback_data.year, callback_data.month)

        await state.update_data(calendar_year=year, calendar_month=month)
        await state.set_state(AppointmentBrowserStates.calendar_month)
        await callback_query.answer('')

        try:
            await callback_query.message.edit_text(
                f"📅 {format_month_label(year, month)}",
                reply_markup=appointment_calendar_kb(year, month),
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise

        await remember_tracked_message(state, callback_query.message)

    @router.callback_query(ApptCalendarDayCB.filter())
    async def pick_calendar_day(
        callback_query: CallbackQuery, callback_data: ApptCalendarDayCB, state: FSMContext,
    ):
        year, month, day = clamp_calendar_date(callback_data.year, callback_data.month, callback_data.day)
        calendar_date = f"{year:04d}-{month:02d}-{day:02d}"

        await state.update_data(
            calendar_date=calendar_date, calendar_year=year, calendar_month=month,
        )
        await state.set_state(AppointmentBrowserStates.calendar_day)

        clinic_id, doctor_id = await appt_mng.resolve_admin_appointment_filter(callback_query.from_user.id)
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
            await render_list(
                callback_query, state, mode="phone", page=1, tab="confirmed",
                clinic_id=clinic_id, doctor_id=doctor_id,
            )
            return

        if data.get("full_name"):
            await state.update_data(search_data={"full_name": data["full_name"]})
            await render_list(
                callback_query, state, mode="search", page=1, tab="confirmed",
                clinic_id=clinic_id, doctor_id=doctor_id,
            )
            return

        await callback_query.answer("Укажите телефон или ФИ для поиска.", show_alert=True)

    # --- Pagination ---

    @router.callback_query(ApptPageCB.filter())
    async def paginate(callback_query: CallbackQuery, callback_data: ApptPageCB, state: FSMContext):
        clinic_id, doctor_id = await appt_mng.resolve_admin_appointment_filter(callback_query.from_user.id)
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
            appointment = await appt_mng.update_status(callback_data.appointment_id, new_status)
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
            await appt_mng.delete_appointment(callback_data.appointment_id)
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

        clinic_id, doctor_id = await appt_mng.resolve_admin_appointment_filter(callback_query.from_user.id)
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

    @router.callback_query(ApptActionCB.filter(F.action == "edit_datetime"))
    async def start_edit_datetime(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
        appointment = await appt_mng.get_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id)
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        await state.update_data(
            appointment_id=callback_data.appointment_id, mode=callback_data.mode, page=callback_data.page,
        )
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

    @router.callback_query(ApptActionCB.filter(F.action == "retry_new_datetime"))
    async def retry_new_datetime(callback_query: CallbackQuery, callback_data: ApptActionCB, state: FSMContext):
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
                callback_data.appointment_id, callback_query.from_user.id, db_datetime,
            )
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка обновления записи: {e}", show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

        if notification_service:
            try:
                message_id = await notification_service.notify_client_appointment_reschedule_proposed(appointment)
                if message_id:
                    await appt_mng.update_proposal_message_id(appointment.id, message_id)
            except Exception as e:
                logger.warning(
                    f"Failed to notify client about proposed time for appointment {callback_data.appointment_id}: {e}"
                )

        old_display = format_datetime_for_display(datetime.fromisoformat(appointment.datetime))

        await callback_query.answer("Предложение отправлено клиенту")
        await callback_query.message.edit_text(
            f"🔁 Текущее время: {old_display} → Предложено: {data.get('appointment_datetime_display')}\n"
            "Ожидаем ответа клиента."
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
            appointment = await appt_mng.update_purpose(callback_data.appointment_id, data["purpose"])
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
            appointment = await appt_mng.update_price(callback_data.appointment_id, data["price"])
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
            appointment = await appt_mng.update_status(callback_data.appointment_id, AppointmentStatus.COMPLETED)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

        await callback_query.answer("Приём завершён")
        await callback_query.message.edit_text(
            build_appointment_card(appointment),
            reply_markup=appointment_card_kb(
                callback_data.appointment_id, callback_data.mode, callback_data.page, status=appointment.status,
            ),
        )
        await remember_tracked_message(state, callback_query.message)

    @router.callback_query(F.data == "noop")
    async def noop_button(callback_query: CallbackQuery):
        await callback_query.answer()

    # --- Shared renderers ---

    async def notify_appointment_changed(appointment, appointment_id: int) -> None:
        if not notification_service:
            return

        try:
            await notification_service.notify_client_appointment_changed(appointment)
        except Exception as e:
            logger.warning(
                f"Failed to notify client about changes for appointment {appointment_id}: {e}"
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
                result = await pagination_service.paginate_all_appointments_by_tab(
                    tab, page, clinic_id, doctor_id
                )
                title = "📒 Все записи"
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
                search_data = None
                if mode in ("search", "phone"):
                    data = await state.get_data()
                    search_data = data.get("search_data") or {}

                result = await pagination_service.paginate_appointments(
                    mode, page, clinic_id, doctor_id, search_data, tab
                )
                titles = {
                    "search": "🔍 Результаты поиска",
                    "phone": "📞 Записи клиента",
                }
                title = titles.get(mode, "📒 Записи")

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
