import asyncio
import logging
from dataclasses import dataclass

from bot.keyboards.admin.name_change_kb import name_change_approval_kb
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


APPROVED_BROADCAST_TEXT = (
    "Уважаемые клиенты! 👋\n\n"
    "Хорошие новости: отпуск и ремонтные работы завершены.\n"
    "Уже с субботы, 5 сентября, мы снова работаем и готовы принимать пациентов.\n\n"
    "Для записи напишите нам в бот! 📲"
)


@dataclass(frozen=True)
class BroadcastSummary:
    sent: int = 0
    failed: int = 0
    skipped: int = 0


class ClientNotificationService:
    def __init__(self, notifier: TelegramNotifier, user_repository: UserRepository) -> None:
        self.notifier = notifier
        self.user_repository = user_repository
        self._broadcast_lock = asyncio.Lock()
        self._broadcast_task: asyncio.Task[BroadcastSummary] | None = None

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

    async def broadcast_clients(self, text: str) -> BroadcastSummary:
        """Best-effort one-time delivery to every client with Telegram access."""
        clients = await self.user_repository.get_all_clients()
        message_text = text if text == APPROVED_BROADCAST_TEXT else escape_html(text)
        summary = BroadcastSummary()

        for client in clients:
            if client.telegram_user_id is None:
                summary = BroadcastSummary(
                    sent=summary.sent,
                    failed=summary.failed,
                    skipped=summary.skipped + 1,
                )
                continue

            try:
                await self.notifier.send_message(
                    chat_id=client.telegram_user_id,
                    text=message_text,
                    reply_markup=None,
                )
            except Exception:
                logger.warning("Failed to send one-time broadcast to a client", exc_info=True)
                summary = BroadcastSummary(
                    sent=summary.sent,
                    failed=summary.failed + 1,
                    skipped=summary.skipped,
                )
            else:
                summary = BroadcastSummary(
                    sent=summary.sent + 1,
                    failed=summary.failed,
                    skipped=summary.skipped,
                )

            await asyncio.sleep(0.05)

        return summary

    async def start_broadcast(self, text: str) -> asyncio.Task[BroadcastSummary] | None:
        """Start one client broadcast unless another batch is still running."""
        async with self._broadcast_lock:
            if self._broadcast_task is not None and not self._broadcast_task.done():
                return None

            task = asyncio.create_task(self._run_broadcast(text))
            self._broadcast_task = task
            return task

    async def _run_broadcast(self, text: str) -> BroadcastSummary:
        try:
            return await self.broadcast_clients(text)
        finally:
            current_task = asyncio.current_task()
            async with self._broadcast_lock:
                if self._broadcast_task is current_task:
                    self._broadcast_task = None
