import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.exceptions.appointment_exceptions import AppointmentNotFoundError
from bot.exceptions.exceptions import BotException
from bot.keyboards.client.appointment_invite_cb import AppointmentInviteActionCB
from bot.keyboards.client.appointment_response_kb import appointment_invite_kb, cancel_confirmation_kb
from bot.models.user import User
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import AppointmentNotificationService
from bot.services.appointment.appointment_scheduler import AppointmentScheduler
from bot.states.client.appointment_states import AppointmentResponseStates
from bot.utils.role import RoleFilter

logger = logging.getLogger(__name__)

_CONFIRM_IRREVERSIBLE_PROMPT = {
    "ru": "Вы уверены? Это действие нельзя отменить.",
    "uz": "Ishonchingiz komilmi? Bu amalni bekor qilib bo'lmaydi.",
}

_APPOINTMENT_CONFIRMED = {
    "ru": "✅ Спасибо! Ваша запись подтверждена",
    "uz": "✅ Rahmat! Yozuvingiz tasdiqlandi",
}

_APPOINTMENT_CANCELLED = {
    "ru": "✅ Ваша запись отменена",
    "uz": "✅ Yozuvingiz bekor qilindi",
}

_APPOINTMENT_NOT_FOUND = {
    "ru": "Запись не найдена",
    "uz": "Yozuv topilmadi",
}

_CANCEL_UNDONE = {
    "ru": "Отмена отменена",
    "uz": "Bekor qilish bekor qilindi",
}

_UNKNOWN_CLIENT_LABEL = {
    "ru": "Неизвестный клиент",
    "uz": "Noma'lum mijoz",
}


def create_client_appointment_invite_router(
    appointment_management_service: AppointmentManagement,
    notification_service: AppointmentNotificationService,
    appointment_scheduler: AppointmentScheduler,
) -> Router:
    router = Router()

    router.message.filter(RoleFilter("client"))
    router.callback_query.filter(RoleFilter("client"))

    @router.callback_query(AppointmentInviteActionCB.filter(F.action == "confirm"))
    async def confirm_invite(callback_query: CallbackQuery, callback_data: AppointmentInviteActionCB, current_user: User):
        lang = current_user.language
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

            await callback_query.message.edit_text(_APPOINTMENT_CONFIRMED.get(lang, _APPOINTMENT_CONFIRMED["ru"]))
            await callback_query.answer()

            if notification_service:
                try:
                    recipients = await appointment_management_service.resolve_notification_recipients(appointment)
                except Exception:
                    recipients = []
                for recipient in recipients:
                    try:
                        await notification_service.notify_admin_confirmation(
                            recipient.telegram_user_id,
                            appointment,
                            client.full_name if client else _UNKNOWN_CLIENT_LABEL.get(lang, _UNKNOWN_CLIENT_LABEL["ru"]),
                        )
                    except Exception:
                        pass  # Graceful fail если не получилось отправить
        except AppointmentNotFoundError:
            await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
        except BotException as e:
            await callback_query.answer(e.localized(lang), show_alert=True)

    @router.callback_query(AppointmentInviteActionCB.filter(F.action == "cancel"))
    async def cancel_invite_ask(
        callback_query: CallbackQuery, callback_data: AppointmentInviteActionCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        appointment_id = callback_data.appointment_id

        await state.set_state(AppointmentResponseStates.confirm_cancel)
        await state.update_data(appointment_id=appointment_id)

        await callback_query.message.edit_text(
            _CONFIRM_IRREVERSIBLE_PROMPT.get(lang, _CONFIRM_IRREVERSIBLE_PROMPT["ru"]),
            reply_markup=cancel_confirmation_kb(
                yes_callback="appt_invite_cancel_yes",
                no_callback="appt_invite_cancel_no",
                lang=lang,
            ),
        )
        await callback_query.answer()

    @router.callback_query(AppointmentResponseStates.confirm_cancel, F.data == "appt_invite_cancel_yes")
    async def cancel_invite_yes(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
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

            await callback_query.message.edit_text(_APPOINTMENT_CANCELLED.get(lang, _APPOINTMENT_CANCELLED["ru"]))
            await callback_query.answer()

            if notification_service:
                try:
                    recipients = await appointment_management_service.resolve_notification_recipients(appointment)
                except Exception:
                    recipients = []
                for recipient in recipients:
                    try:
                        await notification_service.notify_admin_cancellation(
                            recipient.telegram_user_id,
                            appointment,
                            client.full_name if client else _UNKNOWN_CLIENT_LABEL.get(lang, _UNKNOWN_CLIENT_LABEL["ru"]),
                        )
                    except Exception:
                        pass  # Graceful fail если не получилось отправить
        except AppointmentNotFoundError:
            await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
        except BotException as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
        finally:
            await state.clear()

    @router.callback_query(AppointmentResponseStates.confirm_cancel, F.data == "appt_invite_cancel_no")
    async def cancel_invite_no(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        try:
            data = await state.get_data()
            appointment_id = data.get("appointment_id")

            await callback_query.message.edit_text(
                _CANCEL_UNDONE.get(lang, _CANCEL_UNDONE["ru"]),
                reply_markup=appointment_invite_kb(appointment_id, lang),
            )
            await callback_query.answer()
        except BotException as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
        finally:
            await state.clear()

    return router
