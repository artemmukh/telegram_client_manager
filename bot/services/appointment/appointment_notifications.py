from aiogram import Bot
from aiogram.types import ReplyParameters

from bot.exceptions.appointment_exceptions import NotificationDeliveryError
from bot.keyboards.client.appointment_response_kb import appointment_response_kb
from bot.models.appointment import Appointment
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.user_repository import UserRepository

REMINDER_TEXT = "Напоминаем вам о записи."


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
        client = await self.user_repo.get_client_by_id(appointment.client_id)
        client_phone = client.phone if client else "—"

        message_text = (
            f"Клиент {client_name} отменил запись\n\n"
            f"📱 Номер: {client_phone}\n"
            f"Дата и время: {appointment.datetime}\n"
            f"Услуга: {appointment.purpose}"
        )

        await self.bot.send_message(
            chat_id=admin_telegram_id,
            text=message_text
        )

    async def notify_admin_confirmation(
        self,
        admin_telegram_id: int,
        appointment: Appointment,
        client_name: str
    ) -> None:
        """Send confirmation notification to admin."""
        client = await self.user_repo.get_client_by_id(appointment.client_id)
        client_phone = client.phone if client else "—"

        message_text = (
            f"Клиент {client_name} подтвердил запись\n\n"
            f"📱 Номер: {client_phone}\n"
            f"Дата и время: {appointment.datetime}\n"
            f"Услуга: {appointment.purpose}"
        )

        await self.bot.send_message(
            chat_id=admin_telegram_id,
            text=message_text
        )

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
