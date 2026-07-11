from datetime import datetime

from aiogram import Bot
from aiogram.types import ReplyParameters

from bot.exceptions.appointment_exceptions import NotificationDeliveryError
from bot.keyboards.admin.record_management_kb.booking_request_kb import booking_request_kb
from bot.keyboards.admin.record_management_kb.completion_followup_kb import completion_followup_kb
from bot.keyboards.admin.record_management_kb.reschedule_request_kb import reschedule_request_kb
from bot.keyboards.client.appointment_response_kb import appointment_response_kb, reschedule_proposal_kb
from bot.models.appointment import Appointment
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.user_repository import UserRepository
from bot.services.utils.date_parser import format_datetime_for_display

REMINDER_TEXT = "Напоминаем вам о записи."


def _format_datetime_value(value: str) -> str:
    try:
        return format_datetime_for_display(datetime.fromisoformat(value))
    except ValueError:
        return value


class AppointmentNotificationService:
    def __init__(
        self,
        bot: Bot,
        user_repo: UserRepository,
        appointment_repo: AppointmentRepository
    ):
        self.bot = bot
        self.user_repo = user_repo
        self.appointment_repo = appointment_repo

    async def notify_client_appointment_with_buttons(self, appointment: Appointment) -> int | None:
        """Send full appointment notification to client WITH confirmation buttons (on creation).

        Returns the sent message's message_id (to be persisted so later reminders can reply
        to it), or None if the client was not found or has no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return None

        admin = await self.user_repo.get_user_by_id(appointment.doctor_id) if appointment.doctor_id else None
        message_text = self._build_appointment_message(appointment, admin)

        sent_message = await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_markup=appointment_response_kb(appointment.id),
        )

        return sent_message.message_id

    async def notify_client_reminder_without_buttons(self, appointment: Appointment) -> bool:
        """Send short appointment reminder to client as a reply, WITHOUT buttons (24h reminder).

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=REMINDER_TEXT,
            reply_parameters=self._reply_parameters(appointment),
        )

        return True

    async def notify_client_reminder_with_buttons(self, appointment: Appointment) -> bool:
        """Send short appointment reminder to client as a reply, WITH confirmation buttons (2h reminder).

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=REMINDER_TEXT,
            reply_markup=appointment_response_kb(appointment.id),
            reply_parameters=self._reply_parameters(appointment),
        )

        return True

    async def notify_client_appointment_cancelled_by_admin(self, appointment: Appointment) -> bool:
        """Notify client that their appointment was cancelled by an administrator.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text="❌ Ваша запись отменена администратором.",
            reply_parameters=self._reply_parameters(appointment),
        )

        return True

    async def notify_client_booking_request_rejected(self, appointment: Appointment) -> bool:
        """Notify client that their self-booking request was declined by the clinic.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text="❌ Клиника отклонила вашу заявку на запись.",
        )

        return True

    async def notify_client_appointment_changed(self, appointment: Appointment) -> bool:
        """Notify client that details of their appointment (datetime or purpose) were changed.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = (
            "✏️ Детали вашей записи изменены администратором\n\n"
            f"Дата и время: {appointment.datetime}\n"
            f"Услуга: {appointment.purpose}"
        )

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_parameters=self._reply_parameters(appointment),
        )

        return True

    def _reply_parameters(self, appointment: Appointment) -> ReplyParameters | None:
        if appointment.notification_message_id is None:
            return None

        return ReplyParameters(
            message_id=appointment.notification_message_id,
            allow_sending_without_reply=True,
        )

    def _admin_reply_parameters(self, appointment: Appointment) -> ReplyParameters | None:
        if appointment.admin_notification_message_id is None:
            return None

        return ReplyParameters(
            message_id=appointment.admin_notification_message_id,
            allow_sending_without_reply=True,
        )

    async def notify_admin_upcoming_appointment(
        self,
        admin_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> None:
        """Send reminder to admin about upcoming appointment WITHOUT buttons.

        Raises NotificationDeliveryError if the message could not be sent.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)
        client_phone = client.phone if client else "—"

        message_text = (
            f"📌 Предстоящая запись:\n\n"
            f"👤 Клиент: {client_name}\n"
            f"📱 Номер: {client_phone}\n"
            f"📅 Дата и время: {appointment.datetime}\n"
            f"🏥 Услуга: {appointment.purpose}"
        )

        try:
            await self.bot.send_message(
                chat_id=admin_telegram_id,
                text=message_text,
            )
        except Exception as e:
            raise NotificationDeliveryError(
                f"Не удалось отправить напоминание администратору {admin_telegram_id}: {e}"
            ) from e

    async def notify_admin_cancellation(
        self,
        admin_telegram_id: int,
        appointment: Appointment,
        client_name: str
    ) -> None:
        """Send cancellation notification to admin."""
        await self.bot.send_message(
            chat_id=admin_telegram_id,
            text=f"Клиент {client_name} отменил запись.",
            reply_parameters=self._admin_reply_parameters(appointment),
        )

    async def notify_admin_confirmation(
        self,
        admin_telegram_id: int,
        appointment: Appointment,
        client_name: str
    ) -> None:
        """Send confirmation notification to admin."""
        await self.bot.send_message(
            chat_id=admin_telegram_id,
            text=f"Клиент {client_name} подтвердил запись.",
            reply_parameters=self._admin_reply_parameters(appointment),
        )

    async def notify_admin_completion(self, admin_telegram_id: int, appointment: Appointment) -> None:
        """Notify admin that the appointment auto-completed, asking to fill in service details."""
        await self.bot.send_message(
            chat_id=admin_telegram_id,
            text="Приём завершён. Дополнить информацию об услуге?",
            reply_markup=completion_followup_kb(appointment.id),
            reply_parameters=self._admin_reply_parameters(appointment),
        )

    async def notify_staff_new_booking_request(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> int | None:
        """Notify the chosen staff member about a new client self-booking request.

        Sends Confirm / Propose-different-time / Reject action buttons.
        Returns the sent message's message_id on success.
        Raises NotificationDeliveryError if the message could not be sent.
        """
        message_text = (
            f"🆕 Новая заявка на запись\n\n"
            f"👤 Клиент: {client_name}\n"
            f"📅 Дата и время: {appointment.datetime}\n"
            f"📝 Жалоба: {appointment.purpose}"
        )

        try:
            sent_message = await self.bot.send_message(
                chat_id=staff_telegram_id,
                text=message_text,
                reply_markup=booking_request_kb(appointment.id),
            )
        except Exception as e:
            raise NotificationDeliveryError(
                f"Не удалось отправить уведомление специалисту {staff_telegram_id}: {e}"
            ) from e

        return sent_message.message_id

    async def notify_client_pending_request_expired(self, appointment: Appointment) -> bool:
        """Notify client that their unanswered self-booking request has expired.

        The wording depends on whether the clinic had proposed a new time: if it
        did, the request expired because the client never answered that proposal;
        otherwise the clinic itself never responded to the original request.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        if appointment.proposed_datetime is not None:
            text = "⌛ Вы не ответили на предложенное клиникой новое время, заявка на запись истекла."
        else:
            text = "⌛ Ваша заявка на запись истекла без ответа клиники."

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=text,
        )

        return True

    async def notify_client_reschedule_proposed(self, appointment: Appointment) -> int | None:
        """Notify client that the clinic proposed a different time for their request.

        Returns the sent message's message_id (to be persisted so the proposal message
        can later be closed), or None if the client was not found or has no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return None

        message_text = (
            "🔁 Клиника предложила другое время для вашей заявки\n\n"
            f"Предложенное время: {_format_datetime_value(appointment.proposed_datetime)}\n\n"
            "Согласны на новое время?"
        )

        sent_message = await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_markup=reschedule_proposal_kb(appointment.id),
            reply_parameters=self._reply_parameters(appointment),
        )

        return sent_message.message_id

    async def close_reschedule_proposal_message(
        self, chat_id: int, message_id: int, text: str = "Это предложение больше не актуально."
    ) -> None:
        """Edit a stale reschedule-proposal message so it no longer looks actionable."""
        await self.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)

    async def notify_staff_proposal_accepted(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> None:
        """Notify staff that the client accepted the proposed new time."""
        await self.bot.send_message(
            chat_id=staff_telegram_id,
            text=f"✅ Клиент {client_name} согласился на предложенное время.",
            reply_parameters=self._admin_reply_parameters(appointment),
        )

    async def notify_staff_proposal_rejected(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> None:
        """Notify staff that the client rejected the proposed new time."""
        await self.bot.send_message(
            chat_id=staff_telegram_id,
            text=f"❌ Клиент {client_name} отклонил предложенное время.",
            reply_parameters=self._admin_reply_parameters(appointment),
        )

    async def notify_staff_reschedule_requested(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> None:
        """Notify staff that a client wants to reschedule a confirmed appointment.

        Sends Accept / Reject action buttons.
        Raises NotificationDeliveryError if the message could not be sent.
        """
        message_text = (
            f"🔁 Клиент просит перенести запись\n\n"
            f"👤 Клиент: {client_name}\n"
            f"📱 Номер: {appointment.client_phone or '—'}\n"
            f"📅 Текущее время: {_format_datetime_value(appointment.datetime)}\n"
            f"🆕 Предложенное время: {_format_datetime_value(appointment.proposed_datetime)}\n"
            f"📝 Услуга: {appointment.purpose}"
        )

        try:
            await self.bot.send_message(
                chat_id=staff_telegram_id,
                text=message_text,
                reply_markup=reschedule_request_kb(appointment.id),
            )
        except Exception as e:
            raise NotificationDeliveryError(
                f"Не удалось отправить уведомление специалисту {staff_telegram_id}: {e}"
            ) from e

    async def notify_client_reschedule_accepted(self, appointment: Appointment) -> bool:
        """Notify client that the clinic accepted their reschedule request.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = (
            "✅ Клиника приняла ваш перенос записи\n\n"
            f"Новое время: {_format_datetime_value(appointment.datetime)}"
        )

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_parameters=self._reply_parameters(appointment),
        )

        return True

    async def notify_client_reschedule_rejected(self, appointment: Appointment) -> bool:
        """Notify client that the clinic could not accommodate their reschedule request.

        The original appointment remains CONFIRMED and unchanged — this is
        explicitly not a cancellation.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = (
            "❌ Клиника не смогла подтвердить перенос записи\n\n"
            f"Ваша запись остаётся в силе на прежнее время: {_format_datetime_value(appointment.datetime)}"
        )

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_parameters=self._reply_parameters(appointment),
        )

        return True

    async def notify_client_reschedule_request_expired(self, appointment: Appointment) -> bool:
        """Notify client that the clinic did not respond to their reschedule request in time.

        The original appointment remains CONFIRMED and unchanged.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = (
            "⌛ Клиника не ответила на вашу заявку на перенос вовремя\n\n"
            f"Ваша запись остаётся в силе на прежнее время: {_format_datetime_value(appointment.datetime)}"
        )

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_parameters=self._reply_parameters(appointment),
        )

        return True

    def _build_appointment_message(
        self,
        appointment: Appointment,
        admin: User | None = None,
    ) -> str:
        """Build appointment notification message for client."""
        admin_info = ""
        if admin:
            admin_info = f"👨‍⚕️ Администратор: {admin.full_name}\n📱 Номер: {admin.phone or '—'}\n\n"

        return (
            "Вам назначена запись на прием\n\n"
            f"{admin_info}"
            f"Дата и время: {appointment.datetime}\n"
            f"Услуга: {appointment.purpose}\n"
            f"Клиника: {appointment.clinic_name or 'Информация не доступна'}\n\n"
            "Пожалуйста, подтвердите вашу готовность посетить запись"
        )
