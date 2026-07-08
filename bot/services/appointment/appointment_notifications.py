from aiogram import Bot

from bot.keyboards.client.appointment_response_kb import appointment_response_kb
from bot.models.appointment import Appointment
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.user_repository import UserRepository


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

    async def notify_client_appointment(self, appointment: Appointment) -> bool:
        """Send appointment notification to client.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = self._build_appointment_message(appointment)

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_markup=appointment_response_kb(appointment.id)
        )

        return True

    async def notify_client_appointment_without_buttons(self, appointment: Appointment) -> bool:
        """Send appointment reminder to client WITHOUT confirmation buttons (for 24h reminder).

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = self._build_appointment_message(appointment)

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
        )

        return True

    async def notify_client_appointment_with_buttons(self, appointment: Appointment) -> bool:
        """Send appointment reminder to client WITH confirmation buttons (for 2h reminder).

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = self._build_appointment_message(appointment)

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_markup=appointment_response_kb(appointment.id)
        )

        return True

    async def notify_admin_upcoming_appointment(
        self,
        admin_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> bool:
        """Send reminder to admin about upcoming appointment WITHOUT buttons.

        Returns True if message sent, False if send failed.
        """
        message_text = (
            f"📌 Предстоящая запись:\n\n"
            f"👤 Клиент: {client_name}\n"
            f"📅 Дата и время: {appointment.datetime}\n"
            f"🏥 Услуга: {appointment.purpose}"
        )

        try:
            await self.bot.send_message(
                chat_id=admin_telegram_id,
                text=message_text,
            )
            return True
        except Exception:
            return False

    async def notify_admin_cancellation(
        self,
        admin_telegram_id: int,
        appointment: Appointment,
        client_name: str
    ) -> None:
        """Send cancellation notification to admin."""
        message_text = (
            f"Клиент {client_name} отменил запись\n\n"
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
        message_text = (
            f"Клиент {client_name} подтвердил запись\n\n"
            f"Дата и время: {appointment.datetime}\n"
            f"Услуга: {appointment.purpose}"
        )

        await self.bot.send_message(
            chat_id=admin_telegram_id,
            text=message_text
        )

    def _build_appointment_message(self, appointment: Appointment) -> str:
        """Build appointment notification message for client."""
        return (
            "Вам назначена запись на прием\n\n"
            f"Дата и время: {appointment.datetime}\n"
            f"Услуга: {appointment.purpose}\n"
            f"Клиника: {appointment.clinic_name or 'Информация не доступна'}\n\n"
            "Пожалуйста, подтвердите вашу готовность посетить запись"
        )
