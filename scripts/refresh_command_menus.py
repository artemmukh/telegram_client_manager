#!/usr/bin/env python3
"""
One-off migration: refresh the per-chat Telegram command menu for every
already-registered user. `bot/utils/commands.py` fixed a mismatched
`/location` command (now `/geo`) and several handlers gained new slash
commands, but `bot.set_my_commands(..., scope=BotCommandScopeChat(...))` is
only ever called once, at registration time — already-registered users keep
whatever menu was baked in back then. This script re-applies the current
ADMIN_COMMANDS / CLIENT_COMMANDS to every existing user's chat scope.

Usage:
    python scripts/refresh_command_menus.py

Idempotent and safe to re-run at any time: it simply re-sets each user's
command menu to the current ADMIN_COMMANDS/CLIENT_COMMANDS. Users who have
blocked the bot are skipped (Telegram raises TelegramForbiddenError) rather
than aborting the run. Users without a linked Telegram account
(telegram_user_id is None) are skipped as well.
"""

import asyncio
import logging

from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import BotCommandScopeChat

from bot.config.config import load_config
from bot.loader import get_bot
from bot.models.database import Database
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.user_repository import UserRepository
from bot.repositories.user_settings_repository import UserSettingsRepository
from bot.utils.commands import ADMIN_COMMANDS, CLIENT_COMMANDS
from bot.utils.role import Role

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def refresh_command_menus() -> None:
    db = Database(load_config().database_path)
    connection = await db.connect()
    bot = get_bot()

    try:
        user_repo = UserRepository(connection)
        clinic_repo = ClinicRepository(connection)
        user_settings_repo = UserSettingsRepository(connection)

        await user_repo.init()
        await clinic_repo.init()
        await user_settings_repo.init()

        updated = 0
        skipped = 0

        for user in await user_repo.get_all_users():
            if user.telegram_user_id is None:
                skipped += 1
                continue

            commands = ADMIN_COMMANDS if user.role == Role.ADMIN else CLIENT_COMMANDS

            try:
                await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=user.telegram_user_id))
                updated += 1
            except TelegramForbiddenError:
                logger.warning(f"User {user.telegram_user_id} has blocked the bot, skipping")
                skipped += 1

        logger.warning(f"Done. Updated {updated} user(s), skipped {skipped}.")
    finally:
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(refresh_command_menus())
