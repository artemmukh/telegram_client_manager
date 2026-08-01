import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.appointment_exceptions import AppointmentAlreadyDecidedError, AppointmentNotFoundError
from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError
from bot.handlers.utils.admin_utils.appointment_browser_helpers import (
    edit_tracked_message,
    remember_tracked_message,
)
from bot.handlers.utils.admin_utils.appointment_decision_helpers import (
    invalidate_actor_stale_message,
    invalidate_sibling_notifications,
)
from bot.handlers.utils.admin_utils.appointment_helpers import build_appointment_card, datetime_processing
from bot.keyboards.admin.record_management_kb.reschedule_request_cb import RescheduleRequestActionCB
from bot.keyboards.admin.record_management_kb.reschedule_request_kb import (
    reschedule_request_confirm_propose_kb,
    reschedule_request_kb,
    reschedule_request_propose_cancel_kb,
)
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.utils.date_parser import format_datetime_for_db
from bot.states.admin.record_management.reschedule_request_states import RescheduleRequestStates
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.role import RoleFilter

logger = logging.getLogger(__name__)


def create_admin_reschedule_requests_router(
    appointment_repo, user_repo, staff_repo, clinic_repo, notification_service=None, appointment_scheduler=None,
) -> Router:
    router = Router()

    appt_mng = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    async def invalidate_reschedule_siblings(callback_query: CallbackQuery, appointment) -> None:
        if not notification_service:
            return
        try:
            actor = await appt_mng.get_user_by_telegram_id(callback_query.from_user.id)
            decided_by_label = await appt_mng.resolve_decision_label(actor.ID if actor else None)
            outcome_text = appt_mng.resolve_decision_outcome_text(appointment, "reschedule")
            await invalidate_sibling_notifications(
                notification_service, appt_mng, appointment.id, "reschedule",
                callback_query.from_user.id, decided_by_label, outcome_text,
            )
        except Exception as e:
            logger.warning(
                f"Failed to invalidate sibling reschedule notifications for appointment {appointment.id}: {e}"
            )

    async def invalidate_own_stale_reschedule_message(
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
                f"Failed to invalidate own stale reschedule message: {e}"
            )

    @router.callback_query(RescheduleRequestActionCB.filter(F.action == "accept"))
    async def accept_reschedule(callback_query: CallbackQuery, callback_data: RescheduleRequestActionCB):
        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer("Заявка не найдена", show_alert=True)
            return

        try:
            appointment = await appt_mng.accept_client_reschedule(
                callback_data.appointment_id, callback_query.from_user.id
            )
        except AppointmentNotFoundError:
            await callback_query.answer("Заявка не найдена", show_alert=True)
            return
        except AppointmentAlreadyDecidedError as e:
            await callback_query.answer(str(e), show_alert=True)
            await invalidate_own_stale_reschedule_message(callback_query, e)
            return
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

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
        await invalidate_reschedule_siblings(callback_query, appointment)

    @router.callback_query(RescheduleRequestActionCB.filter(F.action == "reject"))
    async def reject_reschedule(callback_query: CallbackQuery, callback_data: RescheduleRequestActionCB):
        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer("Заявка не найдена", show_alert=True)
            return

        try:
            appointment = await appt_mng.reject_client_reschedule(
                callback_data.appointment_id, callback_query.from_user.id
            )
        except AppointmentNotFoundError:
            await callback_query.answer("Заявка не найдена", show_alert=True)
            return
        except AppointmentAlreadyDecidedError as e:
            await callback_query.answer(str(e), show_alert=True)
            await invalidate_own_stale_reschedule_message(callback_query, e)
            return
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

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
        await invalidate_reschedule_siblings(callback_query, appointment)

    @router.callback_query(RescheduleRequestActionCB.filter(F.action == "propose"))
    async def start_propose_datetime(
        callback_query: CallbackQuery, callback_data: RescheduleRequestActionCB, state: FSMContext,
    ):
        await state.update_data(appointment_id=callback_data.appointment_id)
        await state.set_state(RescheduleRequestStates.new_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите новую дату и время (например: завтра в 15:00):",
            reply_markup=reschedule_request_propose_cancel_kb(callback_data.appointment_id),
        )
        await remember_tracked_message(state, callback_query.message)

    @router.message(RescheduleRequestStates.new_datetime, F.text)
    async def process_propose_datetime(message: Message, state: FSMContext):
        if not await datetime_processing(message, state, RescheduleRequestStates.confirm_new_datetime):
            return

        data = await state.get_data()
        await message.delete()
        await edit_tracked_message(
            message.bot, state,
            text=f"Предложить клиенту время: {data.get('appointment_datetime_display')}?",
            reply_markup=reschedule_request_confirm_propose_kb(data["appointment_id"]),
        )

    @router.callback_query(RescheduleRequestActionCB.filter(F.action == "retry_propose_datetime"))
    async def retry_propose_datetime(
        callback_query: CallbackQuery, callback_data: RescheduleRequestActionCB, state: FSMContext,
    ):
        await state.set_state(RescheduleRequestStates.new_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите новую дату и время (например: завтра в 15:00):",
            reply_markup=reschedule_request_propose_cancel_kb(callback_data.appointment_id),
        )

    @router.callback_query(RescheduleRequestActionCB.filter(F.action == "cancel_propose"))
    async def cancel_propose(
        callback_query: CallbackQuery, callback_data: RescheduleRequestActionCB, state: FSMContext,
    ):
        await state.clear()
        appointment = await appt_mng.get_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id)
        if appointment is None:
            await callback_query.answer("Заявка не найдена.", show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_appointment_card(appointment),
            reply_markup=reschedule_request_kb(callback_data.appointment_id),
        )

    @router.callback_query(RescheduleRequestActionCB.filter(F.action == "approve_propose_datetime"))
    async def approve_propose_datetime(
        callback_query: CallbackQuery, callback_data: RescheduleRequestActionCB, state: FSMContext,
    ):
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
                callback_data.appointment_id, callback_query.from_user.id, db_datetime, kind="reschedule",
            )
        except AppointmentNotFoundError:
            await callback_query.answer("Заявка не найдена", show_alert=True)
            return
        except AppointmentAlreadyDecidedError as e:
            await callback_query.answer(str(e), show_alert=True)
            await invalidate_own_stale_reschedule_message(callback_query, e)
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
                f"✅ Время записи изменено на: {data.get('appointment_datetime_display')}"
            )
            await invalidate_reschedule_siblings(callback_query, appointment)
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
                    f"Failed to notify client about new pending time for appointment "
                    f"{callback_data.appointment_id}: {e}"
                )

        await callback_query.answer("Время записи изменено, клиенту отправлено уведомление")
        await callback_query.message.edit_text(
            f"🔁 Клиенту назначено новое время: "
            f"{data.get('appointment_datetime_display')}\nОжидаем подтверждения клиента."
        )
        await invalidate_reschedule_siblings(callback_query, appointment)
        await state.clear()

    return router
