import logging
from datetime import date, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config.clinic_instances import DATEPARSER_BY_INSTANCE as DATA_PARSE_MODE
from bot.exceptions.appointment_exceptions import AppointmentAlreadyDecidedError, AppointmentNotFoundError
from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError
from bot.handlers.utils.admin_utils import appointment_helpers as ah
from bot.handlers.utils.admin_utils.appointment_browser_helpers import (
    edit_tracked_message,
    remember_tracked_message,
)
from bot.handlers.utils.admin_utils.appointment_calendar_helpers import clamp_calendar_date, clamp_month_to_range
from bot.handlers.utils.admin_utils.appointment_decision_helpers import (
    invalidate_actor_stale_message,
    invalidate_sibling_notifications,
)
from bot.handlers.utils.admin_utils.appointment_helpers import (
    build_appointment_card,
    datetime_processing,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import ApptCalendarDayCB, ApptCalendarMonthCB
from bot.keyboards.admin.record_management_kb.appointment_creation_cb import AdminOccupiedSlotCB
from bot.keyboards.admin.record_management_kb.appointment_slot_kb import appointment_slot_grid_kb, occupied_slot_card_kb
from bot.keyboards.admin.record_management_kb.booking_request_cb import BookingRequestActionCB
from bot.keyboards.admin.record_management_kb.booking_request_kb import (
    booking_request_confirm_propose_kb,
    booking_request_kb,
    booking_request_propose_cancel_kb,
)
from bot.keyboards.client.booking_cb import ClientBookSlotCB
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.utils.date_parser import (
    format_datetime_for_confirmation,
    format_datetime_for_db,
    format_datetime_for_display,
    get_current_tashkent_datetime,
)
from bot.states.admin.record_management.booking_negotiation_states import BookingNegotiationStates
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.role import RoleFilter

logger = logging.getLogger(__name__)


def _format_datetime_value(value: str) -> str:
    try:
        return format_datetime_for_display(datetime.fromisoformat(value))
    except ValueError:
        return value


def create_admin_booking_requests_router(
    instance: str,
    appointment_repo, user_repo, staff_repo, clinic_repo, notification_service=None, appointment_scheduler=None,
) -> Router:
    router = Router()

    appt_mng = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    async def invalidate_booking_siblings(callback_query: CallbackQuery, appointment) -> None:
        if not notification_service:
            return
        try:
            actor = await appt_mng.get_user_by_telegram_id(callback_query.from_user.id)
            decided_by_label = await appt_mng.resolve_decision_label(actor.ID if actor else None)
            outcome_text = appt_mng.resolve_decision_outcome_text(appointment, "booking")
            await invalidate_sibling_notifications(
                notification_service, appt_mng, appointment.id, "booking",
                callback_query.from_user.id, decided_by_label, outcome_text,
            )
        except Exception as e:
            logger.warning(
                f"Failed to invalidate sibling booking notifications for appointment {appointment.id}: {e}"
            )

    async def invalidate_own_stale_booking_message(
        callback_query: CallbackQuery, error: AppointmentAlreadyDecidedError
    ) -> None:
        if not notification_service:
            return
        try:
            await invalidate_actor_stale_message(
                notification_service, error,
                callback_query.message.chat.id, callback_query.message.message_id,
            )
        except Exception as e:
            logger.warning(
                f"Failed to invalidate own stale booking message: {e}"
            )

    @router.callback_query(BookingRequestActionCB.filter(F.action == "confirm"))
    async def confirm_request(callback_query: CallbackQuery, callback_data: BookingRequestActionCB):
        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer("Заявка не найдена", show_alert=True)
            return

        try:
            appointment = await appt_mng.confirm_pending_request(
                callback_data.appointment_id, callback_query.from_user.id
            )
        except AppointmentNotFoundError:
            await callback_query.answer("Заявка не найдена", show_alert=True)
            return
        except AppointmentAlreadyDecidedError as e:
            await callback_query.answer(str(e), show_alert=True)
            await invalidate_own_stale_booking_message(callback_query, e)
            return
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

        await notify_client_confirmed(appointment)

        await callback_query.answer("Заявка подтверждена")
        await callback_query.message.edit_text(build_appointment_card(appointment))
        await invalidate_booking_siblings(callback_query, appointment)

    @router.callback_query(BookingRequestActionCB.filter(F.action == "reject"))
    async def reject_request(callback_query: CallbackQuery, callback_data: BookingRequestActionCB):
        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer("Заявка не найдена", show_alert=True)
            return

        try:
            appointment = await appt_mng.reject_pending_request(
                callback_data.appointment_id, callback_query.from_user.id
            )
        except AppointmentNotFoundError:
            await callback_query.answer("Заявка не найдена", show_alert=True)
            return
        except AppointmentAlreadyDecidedError as e:
            await callback_query.answer(str(e), show_alert=True)
            await invalidate_own_stale_booking_message(callback_query, e)
            return
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

        if notification_service:
            try:
                await notification_service.notify_client_booking_request_rejected(appointment)
            except Exception as e:
                logger.warning(
                    f"Failed to notify client about rejection for appointment {callback_data.appointment_id}: {e}"
                )

        await callback_query.answer("Заявка отклонена")
        await callback_query.message.edit_text(build_appointment_card(appointment))
        await invalidate_booking_siblings(callback_query, appointment)

    def propose_calendar_back_target(appointment_id: int) -> tuple[str, str]:
        return (
            BookingRequestActionCB(action="cancel_propose", appointment_id=appointment_id).pack(),
            "❌ Отменить",
        )

    async def enter_propose_calendar(callback_query: CallbackQuery, state: FSMContext, appointment_id: int) -> None:
        await callback_query.answer('')
        today = get_current_tashkent_datetime().date()
        year, month = clamp_month_to_range(today.year, today.month)
        back_callback_data, back_label = propose_calendar_back_target(appointment_id)
        await ah.render_calendar_month(
            callback_query, state, year, month,
            choose_day_state=BookingNegotiationStates.choose_day,
            back_callback_data=back_callback_data, back_label=back_label,
        )

    @router.callback_query(BookingRequestActionCB.filter(F.action == "propose"))
    async def start_propose_datetime(callback_query: CallbackQuery, callback_data: BookingRequestActionCB, state: FSMContext):
        await state.update_data(appointment_id=callback_data.appointment_id)

        if DATA_PARSE_MODE.get(instance) == "slots":
            appointment = await appt_mng.get_appointment_for_admin(
                callback_data.appointment_id, callback_query.from_user.id
            )
            if appointment is None:
                await callback_query.answer("Заявка не найдена.", show_alert=True)
                return

            await state.update_data(staff_user_id=appointment.doctor_id, old_datetime=appointment.datetime)
            await enter_propose_calendar(callback_query, state, callback_data.appointment_id)
            return

        await state.set_state(BookingNegotiationStates.propose_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите новую дату и время (например: завтра в 15:00):",
            reply_markup=booking_request_propose_cancel_kb(callback_data.appointment_id),
        )
        await remember_tracked_message(state, callback_query.message)

    @router.message(BookingNegotiationStates.propose_datetime, F.text)
    async def process_propose_datetime(message: Message, state: FSMContext):
        if not await datetime_processing(message, state, BookingNegotiationStates.confirm_propose_datetime):
            return

        data = await state.get_data()
        await message.delete()
        await edit_tracked_message(
            message.bot, state,
            text=f"Предложить клиенту время: {data.get('appointment_datetime_display')}?",
            reply_markup=booking_request_confirm_propose_kb(data["appointment_id"]),
        )

    # Router registration order matters here: this router is registered before
    # appointment_browser's (see bot/run.py), and browser's
    # ApptCalendarMonthCB/ApptCalendarDayCB handlers are NOT state-filtered.
    # State-filtering these two handlers to choose_day lets a propose-datetime
    # calendar session take priority while its own state is active, and falls
    # through to the browser's calendar handlers otherwise -- keep both the
    # state filter and the router registration order intact.
    @router.callback_query(BookingNegotiationStates.choose_day, ApptCalendarMonthCB.filter())
    async def change_propose_calendar_month(
        callback_query: CallbackQuery, callback_data: ApptCalendarMonthCB, state: FSMContext,
    ):
        year, month = clamp_month_to_range(callback_data.year, callback_data.month)
        data = await state.get_data()
        back_callback_data, back_label = propose_calendar_back_target(data["appointment_id"])
        await ah.render_calendar_month(
            callback_query, state, year, month,
            choose_day_state=BookingNegotiationStates.choose_day,
            back_callback_data=back_callback_data, back_label=back_label,
        )

    async def render_propose_slot_grid(callback_query: CallbackQuery, state: FSMContext, day_iso: str) -> bool:
        day = date.fromisoformat(day_iso)
        now = get_current_tashkent_datetime()
        data = await state.get_data()
        occupancy = await appt_mng.get_day_slot_occupancy(
            data["staff_user_id"], day, now, exclude_appointment_id=data["appointment_id"],
        )

        if not occupancy:
            return False

        await state.update_data(day_iso=day_iso)
        await state.set_state(BookingNegotiationStates.choose_slot)
        await callback_query.message.edit_text(
            f"Выберите время на {day.strftime('%d.%m.%Y')}:",
            reply_markup=appointment_slot_grid_kb(occupancy, cancel_callback_data="admin_book_back_to_day"),
        )
        return True

    @router.callback_query(BookingNegotiationStates.choose_day, ApptCalendarDayCB.filter())
    async def pick_propose_calendar_day(
        callback_query: CallbackQuery, callback_data: ApptCalendarDayCB, state: FSMContext,
    ):
        year, month, day_num = clamp_calendar_date(callback_data.year, callback_data.month, callback_data.day)
        day_iso = date(year, month, day_num).isoformat()

        if not await render_propose_slot_grid(callback_query, state, day_iso):
            await callback_query.answer("На этот день нет доступных слотов.", show_alert=True)
            return

        await callback_query.answer()

    @router.callback_query(BookingNegotiationStates.choose_slot, F.data == "admin_book_back_to_day")
    async def back_to_propose_day_selection(callback_query: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        today = get_current_tashkent_datetime().date()
        year = data.get("calendar_year", today.year)
        month = data.get("calendar_month", today.month)
        back_callback_data, back_label = propose_calendar_back_target(data["appointment_id"])
        await ah.render_calendar_month(
            callback_query, state, year, month,
            choose_day_state=BookingNegotiationStates.choose_day,
            back_callback_data=back_callback_data, back_label=back_label,
        )

    @router.callback_query(BookingNegotiationStates.choose_slot, AdminOccupiedSlotCB.filter())
    async def view_propose_occupied_slot(
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

    @router.callback_query(BookingNegotiationStates.choose_slot, F.data == "admin_book_back_to_slots")
    async def back_to_propose_slot_grid(callback_query: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        await render_propose_slot_grid(callback_query, state, data["day_iso"])
        await callback_query.answer()

    @router.callback_query(BookingNegotiationStates.choose_slot, ClientBookSlotCB.filter())
    async def pick_propose_slot(callback_query: CallbackQuery, callback_data: ClientBookSlotCB, state: FSMContext):
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
        await state.set_state(BookingNegotiationStates.confirm_propose_datetime)

        old_display = format_datetime_for_confirmation(datetime.fromisoformat(data["old_datetime"]))
        await callback_query.message.edit_text(
            f"Предложить клиенту время: {old_display} → {new_display}?",
            reply_markup=booking_request_confirm_propose_kb(data["appointment_id"]),
        )
        await callback_query.answer()

    @router.callback_query(BookingRequestActionCB.filter(F.action == "retry_propose_datetime"))
    async def retry_propose_datetime(callback_query: CallbackQuery, callback_data: BookingRequestActionCB, state: FSMContext):
        if DATA_PARSE_MODE.get(instance) == "slots":
            await enter_propose_calendar(callback_query, state, callback_data.appointment_id)
            return

        await state.set_state(BookingNegotiationStates.propose_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите новую дату и время (например: завтра в 15:00):",
            reply_markup=booking_request_propose_cancel_kb(callback_data.appointment_id),
        )

    @router.callback_query(BookingRequestActionCB.filter(F.action == "cancel_propose"))
    async def cancel_propose(callback_query: CallbackQuery, callback_data: BookingRequestActionCB, state: FSMContext):
        await state.clear()
        appointment = await appt_mng.get_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id)
        if appointment is None:
            await callback_query.answer("Заявка не найдена.", show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_appointment_card(appointment),
            reply_markup=booking_request_kb(callback_data.appointment_id),
        )

    @router.callback_query(BookingRequestActionCB.filter(F.action == "approve_propose_datetime"))
    async def approve_propose_datetime(callback_query: CallbackQuery, callback_data: BookingRequestActionCB, state: FSMContext):
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
            await callback_query.answer("Заявка не найдена", show_alert=True)
            return

        try:
            appointment = await appt_mng.propose_new_datetime(
                callback_data.appointment_id, callback_query.from_user.id, db_datetime, kind="booking",
            )
        except AppointmentNotFoundError:
            await callback_query.answer("Заявка не найдена", show_alert=True)
            return
        except AppointmentAlreadyDecidedError as e:
            await callback_query.answer(str(e), show_alert=True)
            await invalidate_own_stale_booking_message(callback_query, e)
            await state.clear()
            return
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка: {e}", show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

        if appointment.status == AppointmentStatus.CONFIRMED:
            await callback_query.answer("Время записи изменено")
            await callback_query.message.edit_text(
                f"✅ Время записи изменено: {_format_datetime_value(appointment.datetime)}"
            )
            await invalidate_booking_siblings(callback_query, appointment)
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
            f"🔁 Клиенту назначено новое время: {_format_datetime_value(appointment.datetime)}\n"
            "Ожидаем подтверждения клиента."
        )
        await invalidate_booking_siblings(callback_query, appointment)
        await state.clear()

    async def notify_client_confirmed(appointment) -> None:
        if not notification_service:
            return

        try:
            message_id = await notification_service.notify_client_appointment_with_buttons(
                appointment, use_invite_kb=False
            )
            if message_id:
                await appt_mng.update_notification_message_id(appointment.id, message_id)
        except Exception as e:
            logger.warning(
                f"Failed to notify client about confirmation for appointment {appointment.id}: {e}"
            )

    return router
