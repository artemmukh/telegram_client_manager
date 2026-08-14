import asyncio
import logging

from bot.keyboards.admin.name_change_kb import name_change_approval_kb
from bot.keyboards.common.profile_kb import personal_data_broadcast_kb
from bot.models.user import User
from bot.repositories.user_repository import UserRepository
from bot.services.utils.escape_html import escape_html
from bot.services.utils.telegram_notifier import TelegramNotifier

logger = logging.getLogger(__name__)

_NAME_CHANGED_ON_REGISTRATION_TEXT = {
    "ru": (
        "ℹ️ Клиент изменил ФИ при регистрации.\n"
        "Было: {stored_name}\n"
        "Стало: {new_name}\n"
        "Телефон: {client_phone}"
    ),
    "uz": (
        "ℹ️ Mijoz ro'yxatdan o'tishda F.I.Sh.ni o'zgartirdi.\n"
        "Avval: {stored_name}\n"
        "Endi: {new_name}\n"
        "Telefon: {client_phone}"
    ),
}

_NAME_CHANGE_REQUEST_TEXT = {
    "ru": (
        "✏️ Клиент запросил изменение ФИ\n\n"
        "Текущее ФИ: {current_full_name}\n"
        "Новое ФИ: {new_full_name}\n"
        "Телефон: {phone}"
    ),
    "uz": (
        "✏️ Mijoz F.I.Sh.ni o'zgartirishni so'radi\n\n"
        "Joriy F.I.Sh.: {current_full_name}\n"
        "Yangi F.I.Sh.: {new_full_name}\n"
        "Telefon: {phone}"
    ),
}


_PERSONAL_DATA_REQUEST_TEXT = {
"ru": (
        "👋 Пожалуйста, заполните дату рождения и пол — это поможет нам вести ваш профиль точнее.\n\n"
        "Нажмите кнопку ниже, чтобы указать данные.\n\n"
        "Если кнопка не срабатывает, вы всегда можете сделать это через:\n"
        "Профиль → Изменить личные данные → Добавить дату рождения и пол"
    ),
    "uz": (
        "👋 Iltimos, tug'ilgan sanangiz va jinsingizni kiriting — bu profilingizni aniqroq yuritishimizga yordam beradi.\n\n"
        "Ma'lumotlarni kiritish uchun quyidagi tugmani bosing.\n\n"
        "Agar tugma ishlamasa, buni har doim quyidagi orqali qilishingiz mumkin:\n"
        "Profil → Shaxsiy ma'lumotlarni o'zgartirish → Tug'ilgan sana va jinsni qo'shish"
    ),
}


class ClientNotificationService:
    def __init__(self, notifier: TelegramNotifier, user_repository: UserRepository) -> None:
        self.notifier = notifier
        self.user_repository = user_repository

    async def notify_admins_name_changed_on_registration(
        self, clinic_id: int, stored_name: str, new_name: str, client_phone: str
    ) -> None:
        """Best-effort broadcast informing admins that a client changed their name
        during registration. Never raises: a failed delivery to one admin must
        not block delivery to the others."""
        admins = await self.user_repository.get_clinic_notification_recipients(clinic_id)

        for admin in admins:
            if admin.telegram_user_id is None:
                continue

            message_text = _NAME_CHANGED_ON_REGISTRATION_TEXT.get(
                admin.language, _NAME_CHANGED_ON_REGISTRATION_TEXT["ru"]
            ).format(
                stored_name=escape_html(stored_name), new_name=escape_html(new_name), client_phone=client_phone,
            )

            try:
                await self.notifier.send_message(
                    chat_id=admin.telegram_user_id,
                    text=message_text,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to notify admin {admin.telegram_user_id} about name change on registration: {e}"
                )

    async def notify_admins_name_change_request(
        self, user: User, new_full_name: str, user_id: int
    ) -> None:
        """Best-effort broadcast asking admins to approve/reject a client's
        name-change request. Never raises: a failed delivery to one admin must
        not block delivery to the others."""
        admins = await self.user_repository.get_clinic_notification_recipients(user.clinic_id)

        for admin in admins:
            if admin.telegram_user_id is None:
                continue

            message_text = _NAME_CHANGE_REQUEST_TEXT.get(admin.language, _NAME_CHANGE_REQUEST_TEXT["ru"]).format(
                current_full_name=escape_html(user.full_name), new_full_name=escape_html(new_full_name),
                phone=user.phone,
            )
            reply_markup = name_change_approval_kb(user_id, lang=admin.language)

            try:
                await self.notifier.send_message(
                    chat_id=admin.telegram_user_id,
                    text=message_text,
                    reply_markup=reply_markup,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to notify admin {admin.telegram_user_id} about name change request: {e}"
                )

    async def broadcast_personal_data_request(self) -> None:
        """Best-effort broadcast asking clients missing birth date/gender to fill
        them in. Never raises: a failed delivery to one client must not block
        delivery to the others."""
        # text = (
        #     "⚠️ Уважаемые пользователи!\n\n"
        #     "В данный момент в боте могут наблюдаться временные неполадки. "
        #     "Приношу извинения за неудобства. Работа над исправлением уже ведётся."
        # )

        clients = await self.user_repository.get_clients_missing_personal_data()

        for client in clients:
            if client.telegram_user_id is None:
                continue

            message_text = _PERSONAL_DATA_REQUEST_TEXT.get(client.language, _PERSONAL_DATA_REQUEST_TEXT["ru"])
            reply_markup = personal_data_broadcast_kb(lang=client.language)

            try:
                # await self.notifier.send_message(chat_id=client.telegram_user_id, text=text)
                await self.notifier.send_message(
                    chat_id=client.telegram_user_id,
                    text=message_text,
                    reply_markup=reply_markup,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to send personal-data request to client {client.telegram_user_id}: {e}"
                )

            await asyncio.sleep(0.05)
