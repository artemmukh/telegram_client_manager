import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.exceptions.appointment_exceptions import AppointmentNotFoundError
from bot.exceptions.exceptions import BotException
from bot.keyboards.client.appointment_invite_cb import AppointmentInviteActionCB
from bot.keyboards.client.appointment_response_kb import appointment_invite_kb, cancel_confirmation_kb
from bot.repositories.appointment_repository import AppointmentRepository
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import AppointmentNotificationService
from bot.services.appointment.appointment_scheduler import AppointmentScheduler
from bot.states.client.appointment_states import AppointmentResponseStates
from bot.utils.role import RoleFilter

logger = logging.getLogger(__name__)


def create_client_appointment_invite_router(
    appointment_repo: AppointmentRepository,
    appointment_management_service: AppointmentManagement,
    notification_service: AppointmentNotificationService,
    appointment_scheduler: AppointmentScheduler,
) -> Router:
    router = Router()

    router.message.filter(RoleFilter("client"))
    router.callback_query.filter(RoleFilter("client"))

    @router.callback_query(AppointmentInviteActionCB.filter(F.action == "confirm"))
    async def confirm_invite(callback_query: CallbackQuery, callback_data: AppointmentInviteActionCB):
        appointment_id = callback_data.appointment_id

        try:
            await appointment_management_service.confirm_appointment_by_client(
                appointment_id, callback_query.from_user.id
            )

            appointment, client = await appointment_management_service.get_appointment_with_client_info(
                appointment_id
            )

            if appointment_scheduler:
                await appointment_scheduler.resync_appointment_jobs(appointment)

            await callback_query.message.edit_text("✅ Спасибо! Ваша запись подтверждена")
            await callback_query.answer()

            if notification_service and appointment.created_by_telegram_id:
                try:
                    await notification_service.notify_admin_confirmation(
                        appointment.created_by_telegram_id,
                        appointment,
                        client.full_name if client else "Неизвестный клиент",
                    )
                except Exception:
                    pass  # Graceful fail если не получилось отправить
        except AppointmentNotFoundError:
            await callback_query.answer("Запись не найдена", show_alert=True)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)

    @router.callback_query(AppointmentInviteActionCB.filter(F.action == "cancel"))
    async def cancel_invite_ask(
        callback_query: CallbackQuery, callback_data: AppointmentInviteActionCB, state: FSMContext,
    ):
        appointment_id = callback_data.appointment_id

        await state.set_state(AppointmentResponseStates.confirm_cancel)
        await state.update_data(appointment_id=appointment_id)

        await callback_query.message.edit_text(
            "Вы уверены? Это действие нельзя отменить.",
            reply_markup=cancel_confirmation_kb(
                yes_callback="appt_invite_cancel_yes",
                no_callback="appt_invite_cancel_no",
            ),
        )
        await callback_query.answer()

    @router.callback_query(AppointmentResponseStates.confirm_cancel, F.data == "appt_invite_cancel_yes")
    async def cancel_invite_yes(callback_query: CallbackQuery, state: FSMContext):
        try:
            data = await state.get_data()
            appointment_id = data.get("appointment_id")

            await appointment_management_service.cancel_appointment_by_client(
                appointment_id, callback_query.from_user.id, enforce_cutoff=False
            )

            appointment, client = await appointment_management_service.get_appointment_with_client_info(
                appointment_id
            )

            if appointment_scheduler:
                await appointment_scheduler.resync_appointment_jobs(appointment)

            await callback_query.message.edit_text("✅ Ваша запись отменена")
            await callback_query.answer()

            if notification_service and appointment.created_by_telegram_id:
                try:
                    await notification_service.notify_admin_cancellation(
                        appointment.created_by_telegram_id,
                        appointment,
                        client.full_name if client else "Неизвестный клиент",
                    )
                except Exception:
                    pass  # Graceful fail если не получилось отправить
        except AppointmentNotFoundError:
            await callback_query.answer("Запись не найдена", show_alert=True)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
        finally:
            await state.clear()

    @router.callback_query(AppointmentResponseStates.confirm_cancel, F.data == "appt_invite_cancel_no")
    async def cancel_invite_no(callback_query: CallbackQuery, state: FSMContext):
        try:
            data = await state.get_data()
            appointment_id = data.get("appointment_id")

            await callback_query.message.edit_text(
                "Отмена отменена",
                reply_markup=appointment_invite_kb(appointment_id),
            )
            await callback_query.answer()
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
        finally:
            await state.clear()

    return router
