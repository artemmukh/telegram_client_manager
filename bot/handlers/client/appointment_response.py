import logging

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.appointment_exceptions import AppointmentNotFoundError
from bot.exceptions.exceptions import BotException, PaginationError
from bot.handlers.utils.client_utils.appointment_history_helpers import build_history_card_text
from bot.keyboards.client.appointment_history_cb import ClientHistoryCardCB, ClientHistoryPageCB
from bot.keyboards.client.appointment_history_kb import (
    appointment_history_card_kb,
    appointment_history_list_kb,
)
from bot.keyboards.client.appointment_manage_cb import (
    ClientManageActionCB,
    ClientManageCardCB,
    ClientManagePageCB,
)
from bot.keyboards.client.appointment_manage_kb import (
    appointment_manage_card_kb,
    appointment_manage_empty_kb,
    appointment_manage_list_kb,
)
from bot.keyboards.client.appointment_management_kb import client_appointment_management_kb
from bot.keyboards.client.appointment_response_kb import (
    appointment_response_kb,
    cancel_confirmation_kb,
)
from bot.repositories.appointment_repository import AppointmentRepository
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import (
    AppointmentNotificationService,
)
from bot.services.appointment.appointment_pagination_service import AppointmentPaginationService
from bot.states.client.appointment_states import AppointmentResponseStates
from bot.utils.role import RoleFilter

logger = logging.getLogger(__name__)


def create_client_appointment_router(
    appointment_repo: AppointmentRepository,
    appointment_management_service: AppointmentManagement = None,
    notification_service: AppointmentNotificationService = None,
    appointment_scheduler=None,
) -> Router:
    router = Router()

    pagination_service = AppointmentPaginationService(appointment_repo)

    router.message.filter(RoleFilter("client"))
    router.callback_query.filter(RoleFilter("client"))

    @router.message(F.text == "📋 Управление записями")
    async def show_appointment_management(message: Message):
        await message.answer(
            "Выберите действие:",
            reply_markup=client_appointment_management_kb()
        )

    @router.callback_query(F.data == "client_appointment_history")
    async def appointment_history(callback_query: CallbackQuery):
        await render_history_list(callback_query, tab="all", page=1)

    @router.callback_query(ClientHistoryPageCB.filter())
    async def history_paginate(callback_query: CallbackQuery, callback_data: ClientHistoryPageCB):
        await render_history_list(callback_query, callback_data.tab, callback_data.page)

    @router.callback_query(ClientHistoryCardCB.filter())
    async def history_open_card(callback_query: CallbackQuery, callback_data: ClientHistoryCardCB):
        await render_history_card(
            callback_query, callback_data.appointment_id, callback_data.tab, callback_data.page,
        )

    @router.callback_query(F.data == "client_appointment_menu")
    async def back_to_appointment_menu(callback_query: CallbackQuery, state: FSMContext):
        await state.clear()
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Выберите действие:", reply_markup=client_appointment_management_kb(),
        )

    @router.callback_query(F.data == "noop")
    async def noop_button(callback_query: CallbackQuery):
        await callback_query.answer()

    # Handler for appointment confirmation
    if appointment_management_service and notification_service:
        @router.callback_query(F.data == "client_manage_appointment")
        async def manage_appointment(callback_query: CallbackQuery):
            await render_manage_list(callback_query, page=1)

        @router.callback_query(ClientManagePageCB.filter())
        async def manage_paginate(callback_query: CallbackQuery, callback_data: ClientManagePageCB):
            await render_manage_list(callback_query, callback_data.page)

        @router.callback_query(ClientManageCardCB.filter())
        async def manage_open_card(callback_query: CallbackQuery, callback_data: ClientManageCardCB):
            await render_manage_card(callback_query, callback_data.appointment_id, callback_data.page)

        @router.callback_query(ClientManageActionCB.filter())
        async def manage_action(callback_query: CallbackQuery, callback_data: ClientManageActionCB):
            appointment_id = callback_data.appointment_id
            page = callback_data.page

            if callback_data.action == "confirm":
                try:
                    await appointment_management_service.confirm_appointment_by_client(
                        appointment_id, callback_query.from_user.id
                    )

                    appointment, client = await appointment_management_service.get_appointment_with_client_info(
                        appointment_id
                    )

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
                return

            if callback_data.action == "cancel_ask":
                await callback_query.message.edit_text(
                    "Вы уверены? Это действие нельзя отменить.",
                    reply_markup=cancel_confirmation_kb(
                        yes_callback=ClientManageActionCB(
                            action="cancel_yes", appointment_id=appointment_id, page=page
                        ).pack(),
                        no_callback=ClientManageActionCB(
                            action="cancel_no", appointment_id=appointment_id, page=page
                        ).pack(),
                    ),
                )
                await callback_query.answer()
                return

            if callback_data.action == "cancel_yes":
                try:
                    await appointment_management_service.cancel_appointment_by_client(
                        appointment_id, callback_query.from_user.id, enforce_cutoff=True
                    )

                    appointment, client = await appointment_management_service.get_appointment_with_client_info(
                        appointment_id
                    )

                    if appointment_scheduler:
                        await appointment_scheduler.cancel_appointment_reminders(appointment_id)
                        await appointment_scheduler.cancel_appointment_completions(appointment_id)
                        await appointment_scheduler.cancel_pending_expiry(appointment_id)

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
                return

            if callback_data.action == "cancel_no":
                await render_manage_card(callback_query, appointment_id, page)
                return

            if callback_data.action == "accept_proposal":
                try:
                    appointment = await appointment_management_service.accept_proposed_datetime(
                        appointment_id, callback_query.from_user.id
                    )

                    _, client = await appointment_management_service.get_appointment_with_client_info(
                        appointment_id
                    )

                    if appointment_scheduler:
                        await appointment_scheduler.cancel_pending_expiry(appointment_id)
                        await appointment_scheduler.schedule_appointment_reminders(appointment)
                        await appointment_scheduler.schedule_appointment_completion(appointment)

                    await callback_query.message.edit_text(
                        "✅ Вы согласились на новое время. Запись подтверждена."
                    )
                    await callback_query.answer()

                    if notification_service and appointment.created_by_telegram_id:
                        try:
                            await notification_service.notify_staff_proposal_accepted(
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
                return

            if callback_data.action == "reject_proposal":
                try:
                    appointment = await appointment_management_service.reject_proposed_datetime(
                        appointment_id, callback_query.from_user.id
                    )

                    _, client = await appointment_management_service.get_appointment_with_client_info(
                        appointment_id
                    )

                    if appointment_scheduler:
                        await appointment_scheduler.cancel_pending_expiry(appointment_id)

                    await callback_query.message.edit_text(
                        "❌ Вы отклонили предложенное время. Если запись всё ещё нужна, "
                        "свяжитесь с клиникой или отправьте новую заявку."
                    )
                    await callback_query.answer()

                    if notification_service and appointment.created_by_telegram_id:
                        try:
                            await notification_service.notify_staff_proposal_rejected(
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
                return

        @router.callback_query(F.data.startswith("appt_confirm:"))
        async def handle_appointment_confirm(callback_query: CallbackQuery):
            """Handle appointment confirmation button."""
            try:
                appointment_id = int(callback_query.data.split(":")[1])

                # Update status to CONFIRMED
                appointment = await appointment_management_service.confirm_appointment_by_client(
                    appointment_id, callback_query.from_user.id
                )

                # Get appointment and client info for notification
                appointment, client = await appointment_management_service.get_appointment_with_client_info(
                    appointment_id
                )

                # Send success message to client
                await callback_query.message.edit_text("✅ Спасибо! Ваша запись подтверждена")
                await callback_query.answer()

                # Notify admin about confirmation
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
                    reply_markup=cancel_confirmation_kb(
                        yes_callback="appt_cancel_confirm_yes",
                        no_callback="appt_cancel_confirm_no",
                    ),
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

                # Update status to CANCELLED (2h cutoff does not apply to the
                # reminder-triggered flow)
                appointment = await appointment_management_service.cancel_appointment_by_client(
                    appointment_id, callback_query.from_user.id, enforce_cutoff=False
                )

                # Get appointment and client info for notification
                appointment, client = await appointment_management_service.get_appointment_with_client_info(
                    appointment_id
                )

                if appointment_scheduler:
                    await appointment_scheduler.cancel_appointment_reminders(appointment_id)
                    await appointment_scheduler.cancel_appointment_completions(appointment_id)
                    await appointment_scheduler.cancel_pending_expiry(appointment_id)

                await callback_query.message.edit_text("✅ Ваша запись отменена")
                await callback_query.answer()

                # Notify admin about cancellation
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

    async def render_history_list(callback_query: CallbackQuery, tab: str, page: int) -> None:
        try:
            result = await pagination_service.paginate_client_appointments(
                callback_query.from_user.id, tab, page,
            )

            titles = {"upcoming": "📅 Предстоящие", "past": "📋 Прошедшие", "all": "📖 Все записи"}
            title = titles.get(tab, "📖 История записей")
            text = f"{title} ({result.current_page} из {result.total_pages}) | Всего: {result.total_count}"

            await callback_query.message.edit_text(
                text,
                reply_markup=appointment_history_list_kb(
                    result.items, tab, result.current_page, result.total_pages,
                ),
            )
            await callback_query.answer()
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback_query.answer()
            else:
                logger.warning(f"TelegramBadRequest in render_history_list: {e}")
                await callback_query.answer("Ошибка редактирования сообщения", show_alert=False)
        except PaginationError as e:
            logger.warning(f"Pagination error in render_history_list: {e}")
            await callback_query.answer(str(e), show_alert=True)
        except Exception as e:
            logger.exception(f"Unexpected error in render_history_list: {e}")
            await callback_query.answer("Произошла непредвиденная ошибка", show_alert=True)

    async def render_history_card(
        callback_query: CallbackQuery, appointment_id: int, tab: str, page: int,
    ) -> None:
        appointment = await appointment_management_service.get_appointment_for_client(
            appointment_id, callback_query.from_user.id,
        )
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_history_card_text(appointment),
            reply_markup=appointment_history_card_kb(tab, page),
        )

    async def render_manage_list(callback_query: CallbackQuery, page: int) -> None:
        try:
            result = await pagination_service.paginate_active_client_appointments(
                callback_query.from_user.id, page,
            )

            if result.total_count == 0:
                await callback_query.message.edit_text(
                    "У вас нет активных записей.",
                    reply_markup=appointment_manage_empty_kb(),
                )
                await callback_query.answer()
                return

            text = f"🔧 Активные записи ({result.current_page} из {result.total_pages}) | Всего: {result.total_count}"

            await callback_query.message.edit_text(
                text,
                reply_markup=appointment_manage_list_kb(
                    result.items, result.current_page, result.total_pages,
                ),
            )
            await callback_query.answer()
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback_query.answer()
            else:
                logger.warning(f"TelegramBadRequest in render_manage_list: {e}")
                await callback_query.answer("Ошибка редактирования сообщения", show_alert=False)
        except PaginationError as e:
            logger.warning(f"Pagination error in render_manage_list: {e}")
            await callback_query.answer(str(e), show_alert=True)
        except Exception as e:
            logger.exception(f"Unexpected error in render_manage_list: {e}")
            await callback_query.answer("Произошла непредвиденная ошибка", show_alert=True)

    async def render_manage_card(callback_query: CallbackQuery, appointment_id: int, page: int) -> None:
        appointment = await appointment_management_service.get_appointment_for_client(
            appointment_id, callback_query.from_user.id,
        )
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_history_card_text(appointment),
            reply_markup=appointment_manage_card_kb(appointment, page),
        )

    return router
