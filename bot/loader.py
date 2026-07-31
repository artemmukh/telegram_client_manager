from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from bot.config.config import load_config
from bot.services.utils.telegram_notifier import TelegramNotifier

_bot: Bot | None = None
_notifier: TelegramNotifier | None = None


def get_bot() -> Bot:
    """Get or create the Bot singleton instance.

    This function ensures a single Bot instance exists throughout the application.
    Used by job functions to access the bot without circular imports.
    """
    global _bot
    if _bot is None:
        config = load_config()
        _bot = Bot(token=config.bot_token, default=DefaultBotProperties( parse_mode="HTML"))
    return _bot


def get_notifier() -> TelegramNotifier:
    """Get or create the TelegramNotifier singleton instance.

    Wraps get_bot()'s Bot instance so services depend on the notifier
    adapter instead of the raw aiogram Bot.
    """
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier(get_bot())
    return _notifier
