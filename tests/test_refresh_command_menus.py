"""Tests for the one-off scripts/refresh_command_menus.py script.

Follows the tempfile.TemporaryDirectory() convention established in
test_migrate_users_created_at_timezone.py (pytest's own tmp_path is unusable
on this Windows dev machine due to broken ACLs on its base temp directory).

The script's I/O entrypoints (load_config, get_bot) are module-level
functions, not repositories -- stubbing them here does not conflict with the
repo-test-fakes convention (tests/conftest.py), which only covers
Fake*Repository substitutes for repository classes.
"""
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest
from aiogram.exceptions import TelegramForbiddenError

import scripts.refresh_command_menus as refresh_command_menus_module
from bot.models.user import User
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.user_repository import UserRepository
from bot.repositories.user_settings_repository import UserSettingsRepository
from bot.utils.commands import ADMIN_COMMANDS, CLIENT_COMMANDS
from bot.utils.role import Role


class FakeConfig:
    def __init__(self, database_path):
        self.database_path = str(database_path)
        self.instance = "zb"


class FakeBot:
    def __init__(self, forbidden_chat_ids=None):
        self.forbidden_chat_ids = set(forbidden_chat_ids or set())
        self.calls: list[tuple[list, int]] = []
        self.session = MagicMock()
        self.session.close = AsyncMock()

    async def set_my_commands(self, commands, scope):
        if scope.chat_id in self.forbidden_chat_ids:
            raise TelegramForbiddenError(MagicMock(), "Forbidden: bot was blocked by the user")
        self.calls.append((commands, scope.chat_id))


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir) / "data" / "data_base.db"


async def _seed_users(path: Path, users: list[User]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = await aiosqlite.connect(path)
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        await ClinicRepository(connection).init("zb")
        user_repo = UserRepository(connection)
        await user_repo.init()
        await UserSettingsRepository(connection).init()

        for user in users:
            await user_repo.create_user(user)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_refresh_command_menus_sets_role_specific_commands_and_skips_unlinked_and_blocked(
    db_path, monkeypatch,
):
    admin = User(
        full_name="Админ Один", phone="+998901111101", role=Role.ADMIN, telegram_user_id=101,
    )
    client = User(
        full_name="Клиент Один", phone="+998901111102", role=Role.CLIENT, telegram_user_id=102,
    )
    unlinked_client = User(
        full_name="Клиент Два", phone="+998901111103", role=Role.CLIENT, telegram_user_id=None,
    )
    blocked_client = User(
        full_name="Клиент Три", phone="+998901111104", role=Role.CLIENT, telegram_user_id=103,
    )
    await _seed_users(db_path, [admin, client, unlinked_client, blocked_client])

    fake_bot = FakeBot(forbidden_chat_ids={103})
    monkeypatch.setattr(refresh_command_menus_module, "load_config", lambda: FakeConfig(db_path))
    monkeypatch.setattr(refresh_command_menus_module, "get_bot", lambda: fake_bot)

    await refresh_command_menus_module.refresh_command_menus()

    assert (ADMIN_COMMANDS, 101) in fake_bot.calls
    assert (CLIENT_COMMANDS, 102) in fake_bot.calls
    # Unlinked (telegram_user_id is None) and blocked (TelegramForbiddenError)
    # users must not receive a set_my_commands call.
    assert all(chat_id not in (None, 103) for _, chat_id in fake_bot.calls)
    assert len(fake_bot.calls) == 2

    fake_bot.session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_command_menus_is_noop_when_no_users_exist(db_path, monkeypatch):
    await _seed_users(db_path, [])

    fake_bot = FakeBot()
    monkeypatch.setattr(refresh_command_menus_module, "load_config", lambda: FakeConfig(db_path))
    monkeypatch.setattr(refresh_command_menus_module, "get_bot", lambda: fake_bot)

    await refresh_command_menus_module.refresh_command_menus()

    assert fake_bot.calls == []
    fake_bot.session.close.assert_awaited_once()
