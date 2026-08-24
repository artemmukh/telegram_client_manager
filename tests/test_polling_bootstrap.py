"""Tests for the polling bootstrap sequence."""

import pytest
from aiogram.types import BotCommandScopeDefault
from bot.utils.polling import prepare_polling

from bot.utils.commands import DEFAULT_COMMANDS


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def delete_webhook(self, *, drop_pending_updates: bool) -> None:
        self.calls.append(("delete_webhook", drop_pending_updates))

    async def set_my_commands(self, commands, scope) -> None:
        self.calls.append(("set_my_commands", commands, scope))


@pytest.mark.asyncio
async def test_prepare_polling_deletes_webhook_before_setting_default_commands():
    bot = FakeBot()

    await prepare_polling(bot)

    assert len(bot.calls) == 2
    assert bot.calls[0] == ("delete_webhook", False)

    name, commands, scope = bot.calls[1]
    assert name == "set_my_commands"
    assert commands is DEFAULT_COMMANDS
    assert isinstance(scope, BotCommandScopeDefault)
