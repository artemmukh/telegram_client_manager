import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.exceptions.appointment_exceptions import AppointmentNotFoundError
from bot.exceptions.exceptions import BotException
from bot.handlers.utils.admin_utils.appointment_helpers import build_appointment_card
from bot.keyboards.admin.record_management_kb.reschedule_request_cb import RescheduleRequestActionCB
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.utils.role import RoleFilter

logger = logging.getLogger(__name__)


def create_admin_reschedule_requests_router(
    appointment_repo, user_repo, staff_repo, clinic_repo, notification_service=None, appointment_scheduler=None,
) -> Router:
    router = Router()

    appt_mng = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    @router.callback_query(RescheduleRequestActionCB.filter(F.action == "accept"))
    async def accept_reschedule(callback_query: CallbackQuery, callback_data: RescheduleRequestActionCB):
        try:
            appointment = await appt_mng.accept_client_reschedule(
                callback_data.appointment_id, callback_query.from_user.id
            )
        except AppointmentNotFoundError:
            await callback_query.answer("Заявка не найдена", show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.cancel_reschedule_expiry(callback_data.appointment_id)
            await appointment_scheduler.cancel_appointment_reminders(callback_data.appointment_id)
            await appointment_scheduler.schedule_appointment_reminders(appointment)
            await appointment_scheduler.cancel_appointment_completions(callback_data.appointment_id)
            await appointment_scheduler.schedule_appointment_completion(appointment)

        if notification_service:
            try:
                await notification_service.notify_client_reschedule_accepted(appointment)
            except Exception as e:
                logger.warning(
                    f"Failed to notify client about accepted reschedule for appointment "
                    f"{callback_data.appointment_id}: {e}"
                )

        await callback_query.answer("Перенос принят")
        await callback_query.message.edit_text(build_appointment_card(appointment))

    @router.callback_query(RescheduleRequestActionCB.filter(F.action == "reject"))
    async def reject_reschedule(callback_query: CallbackQuery, callback_data: RescheduleRequestActionCB):
        try:
            appointment = await appt_mng.reject_client_reschedule(
                callback_data.appointment_id, callback_query.from_user.id
            )
        except AppointmentNotFoundError:
            await callback_query.answer("Заявка не найдена", show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.cancel_reschedule_expiry(callback_data.appointment_id)

        if notification_service:
            try:
                await notification_service.notify_client_reschedule_rejected(appointment)
            except Exception as e:
                logger.warning(
                    f"Failed to notify client about rejected reschedule for appointment "
                    f"{callback_data.appointment_id}: {e}"
                )

        await callback_query.answer("Перенос отклонён")
        await callback_query.message.edit_text(build_appointment_card(appointment))

    return router
