from aiogram import Bot
from aiogram.types import BotCommandScopeDefault

from bot.utils.commands import DEFAULT_COMMANDS


async def prepare_polling(bot: Bot) -> None:
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.set_my_commands(DEFAULT_COMMANDS, scope=BotCommandScopeDefault())
