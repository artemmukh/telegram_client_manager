from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from bot.config.config import load_config

_bot: Bot | None = None


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
