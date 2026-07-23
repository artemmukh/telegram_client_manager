import asyncio
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from bot.models.user import User
from bot.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class ClientNotificationService:
    def __init__(self, bot: Bot, user_repository: UserRepository) -> None:
        self.bot = bot
        self.user_repository = user_repository

    async def notify_admins_name_changed_on_registration(
        self, clinic_id: int, stored_name: str, new_name: str, client_phone: str
    ) -> None:
        """Best-effort broadcast informing admins that a client changed their name
        during registration. Never raises: a failed delivery to one admin must
        not block delivery to the others."""
        message_text = (
            "ℹ️ Клиент изменил ФИ при регистрации.\n"
            f"Было: {stored_name}\n"
            f"Стало: {new_name}\n"
            f"Телефон: {client_phone}"
        )

        admins = await self.user_repository.get_staff_users_by_clinic_id(clinic_id)

        for admin in admins:
            if admin.telegram_user_id is None:
                continue

            try:
                await self.bot.send_message(
                    chat_id=admin.telegram_user_id,
                    text=message_text,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to notify admin {admin.telegram_user_id} about name change on registration: {e}"
                )

    async def notify_admins_name_change_request(
        self, user: User, new_full_name: str, reply_markup: InlineKeyboardMarkup
    ) -> None:
        """Best-effort broadcast asking admins to approve/reject a client's
        name-change request. Never raises: a failed delivery to one admin must
        not block delivery to the others."""
        message_text = (
            "✏️ Клиент запросил изменение ФИ\n\n"
            f"Текущее ФИ: {user.full_name}\n"
            f"Новое ФИ: {new_full_name}\n"
            f"Телефон: {user.phone}"
        )

        admins = await self.user_repository.get_staff_users_by_clinic_id(user.clinic_id)

        for admin in admins:
            if admin.telegram_user_id is None:
                continue

            try:
                await self.bot.send_message(
                    chat_id=admin.telegram_user_id,
                    text=message_text,
                    reply_markup=reply_markup,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to notify admin {admin.telegram_user_id} about name change request: {e}"
                )

    async def broadcast_personal_data_request(self, reply_markup: InlineKeyboardMarkup) -> None:
        """Best-effort broadcast asking clients missing birth date/gender to fill
        them in. Never raises: a failed delivery to one client must not block
        delivery to the others."""
        # text = (
        #     "⚠️ Уважаемые пользователи!\n\n"
        #     "В данный момент в боте могут наблюдаться временные неполадки. "
        #     "Приношу извинения за неудобства. Работа над исправлением уже ведётся."
        # )

        message_text = (
            "👋 Пожалуйста, заполните дату рождения и пол — это поможет нам вести ваш профиль точнее.\n\n"
            "Нажмите кнопку ниже, чтобы указать данные.\n\n"
            "Если кнопка не срабатывает, вы всегда можете сделать это через:\n"
            "Профиль → Изменить личные данные → Добавить дату рождения и пол"
        )

        clients = await self.user_repository.get_clients_missing_personal_data()

        for client in clients:
            if client.telegram_user_id is None:
                continue

            try:
                # await self.bot.send_message(chat_id=client.telegram_user_id, text=text)
                await self.bot.send_message(
                    chat_id=client.telegram_user_id,
                    text=message_text,
                    reply_markup=reply_markup,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to send personal-data request to client {client.telegram_user_id}: {e}"
                )

            await asyncio.sleep(0.05)
