import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.appointment_exceptions import AppointmentNotFoundError
from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError
from bot.handlers.utils.admin_utils.appointment_browser_helpers import (
    edit_tracked_message,
    remember_tracked_message,
)
from bot.handlers.utils.admin_utils.appointment_helpers import (
    build_appointment_card,
    datetime_processing,
)
from bot.keyboards.admin.record_management_kb.booking_request_cb import BookingRequestActionCB
from bot.keyboards.admin.record_management_kb.booking_request_kb import (
    booking_request_confirm_propose_kb,
    booking_request_kb,
    booking_request_propose_cancel_kb,
)
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.utils.date_parser import format_datetime_for_db, format_datetime_for_display
from bot.states.admin.record_management.booking_negotiation_states import BookingNegotiationStates
from bot.utils.role import RoleFilter

logger = logging.getLogger(__name__)


def _format_datetime_value(value: str) -> str:
    try:
        return format_datetime_for_display(datetime.fromisoformat(value))
    except ValueError:
        return value


def create_admin_booking_requests_router(
    appointment_repo, user_repo, staff_repo, clinic_repo, notification_service=None, appointment_scheduler=None,
) -> Router:
    router = Router()

    appt_mng = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

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
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

        await notify_client_confirmed(appointment)

        await callback_query.answer("Заявка подтверждена")
        await callback_query.message.edit_text(build_appointment_card(appointment))

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

    @router.callback_query(BookingRequestActionCB.filter(F.action == "propose"))
    async def start_propose_datetime(callback_query: CallbackQuery, callback_data: BookingRequestActionCB, state: FSMContext):
        await state.update_data(appointment_id=callback_data.appointment_id)
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

    @router.callback_query(BookingRequestActionCB.filter(F.action == "retry_propose_datetime"))
    async def retry_propose_datetime(callback_query: CallbackQuery, callback_data: BookingRequestActionCB, state: FSMContext):
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
                callback_data.appointment_id, callback_query.from_user.id, db_datetime,
            )
        except AppointmentNotFoundError:
            await callback_query.answer("Заявка не найдена", show_alert=True)
            return
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка: {e}", show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

        if notification_service:
            try:
                message_id = await notification_service.notify_client_reschedule_proposed(appointment)
                if message_id:
                    await appt_mng.update_proposal_message_id(appointment.id, message_id)
            except Exception as e:
                logger.warning(
                    f"Failed to notify client about proposed time for appointment {callback_data.appointment_id}: {e}"
                )

        await callback_query.answer("Предложение отправлено клиенту")
        await callback_query.message.edit_text(
            f"🔁 Клиенту предложено новое время: {_format_datetime_value(appointment.proposed_datetime)}\n"
            "Ожидаем ответа клиента."
        )
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
