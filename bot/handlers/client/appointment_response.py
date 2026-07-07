from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.appointment_exceptions import AppointmentNotFoundError
from bot.exceptions.exceptions import BotException
from bot.keyboards.client.appointment_management_kb import client_appointment_management_kb
from bot.keyboards.client.appointment_response_kb import (
    appointment_response_kb,
    cancel_confirmation_kb,
)
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.user_repository import UserRepository
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import (
    AppointmentNotificationService,
)
from bot.states.client.appointment_states import AppointmentResponseStates
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.role import RoleFilter


def create_client_appointment_router(
    bot: Bot = None,
    user_repo: UserRepository = None,
    appointment_repo: AppointmentRepository = None,
    appointment_management_service: AppointmentManagement = None,
    notification_service: AppointmentNotificationService = None,
) -> Router:
    router = Router()

    router.message.filter(RoleFilter("client"))
    router.callback_query.filter(RoleFilter("client"))

    @router.message(F.text == "📋 Управление записями")
    async def show_appointment_management(message: Message):
        await message.answer(
            "Выберите действие:",
            reply_markup=client_appointment_management_kb()
        )

    @router.callback_query(F.data == "client_book_appointment")
    async def book_appointment(callback_query: CallbackQuery):
        await callback_query.answer()
        await callback_query.message.answer("Функция записи скоро будет доступна...")

    @router.callback_query(F.data == "client_appointment_history")
    async def appointment_history(callback_query: CallbackQuery):
        await callback_query.answer()
        await callback_query.message.answer("Функция истории скоро будет доступна...")

    @router.callback_query(F.data == "client_manage_appointment")
    async def manage_appointment(callback_query: CallbackQuery):
        await callback_query.answer()
        await callback_query.message.answer("Функция управления скоро будет доступна...")

    # Handler for appointment confirmation
    if appointment_management_service and notification_service:
        @router.callback_query(F.data.startswith("appt_confirm:"))
        async def handle_appointment_confirm(callback_query: CallbackQuery):
            """Handle appointment confirmation button."""
            try:
                appointment_id = int(callback_query.data.split(":")[1])

                # Update status to CONFIRMED
                appointment = await appointment_management_service.update_status(
                    appointment_id, AppointmentStatus.CONFIRMED
                )

                # Get appointment and client info for notification
                appointment, client = await appointment_management_service.get_appointment_with_client_info(
                    appointment_id
                )

                # Send success message to client
                await callback_query.message.edit_text("✅ Спасибо! Ваша запись подтверждена")
                await callback_query.answer()

            except AppointmentNotFoundError:
                await callback_query.answer("Запись не найдена", show_alert=True)
            except BotException as e:
                await callback_query.answer(str(e), show_alert=True)

        # Handler for appointment cancellation (shows confirmation dialog)
        @router.callback_query(F.data.startswith("appt_cancel:"))
        async def handle_appointment_cancel(callback_query: CallbackQuery, state: FSMContext):
            """Handle appointment cancellation button (show confirmation dialog)."""
            try:
                appointment_id = int(callback_query.data.split(":")[1])

                await state.set_state(AppointmentResponseStates.confirm_cancel)
                await state.update_data(appointment_id=appointment_id)

                await callback_query.message.edit_text(
                    "Вы уверены? Это действие нельзя отменить.",
                    reply_markup=cancel_confirmation_kb(),
                )
                await callback_query.answer()
            except BotException as e:
                await callback_query.answer(str(e), show_alert=True)

        # Handler for cancellation confirmation YES
        @router.callback_query(AppointmentResponseStates.confirm_cancel, F.data == "appt_cancel_confirm_yes")
        async def handle_cancel_confirmation_yes(callback_query: CallbackQuery, state: FSMContext):
            """Confirm cancellation."""
            try:
                data = await state.get_data()
                appointment_id = data.get("appointment_id")

                # Update status to CANCELLED
                appointment = await appointment_management_service.update_status(
                    appointment_id, AppointmentStatus.CANCELLED
                )

                # Get appointment and client info for notification
                appointment, client = await appointment_management_service.get_appointment_with_client_info(
                    appointment_id
                )

                await callback_query.message.edit_text("✅ Ваша запись отменена")
                await callback_query.answer()

            except AppointmentNotFoundError:
                await callback_query.answer("Запись не найдена", show_alert=True)
            except BotException as e:
                await callback_query.answer(str(e), show_alert=True)
            finally:
                await state.clear()

        # Handler for cancellation confirmation NO
        @router.callback_query(AppointmentResponseStates.confirm_cancel, F.data == "appt_cancel_confirm_no")
        async def handle_cancel_confirmation_no(callback_query: CallbackQuery, state: FSMContext):
            """Cancel the cancellation (go back)."""
            try:
                data = await state.get_data()
                appointment_id = data.get("appointment_id")

                await callback_query.message.edit_text(
                    "Отмена отменена",
                    reply_markup=appointment_response_kb(appointment_id),
                )
                await callback_query.answer()
            except BotException as e:
                await callback_query.answer(str(e), show_alert=True)
            finally:
                await state.clear()

    return router
