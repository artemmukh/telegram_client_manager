"""Tests for the non-blocking same-name duplicate warning in client creation.

Flow:
- client_creation_finish finds an exact-name duplicate within the same
  clinic -> shows a Да/Нет warning instead of creating immediately.
- "Да" -> creates the client (same as if there had been no duplicate).
- "Нет" -> returns to confirm_create without creating anything.
- No duplicate found -> creates directly, as before.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers.admin.client_management.client_creation import create_admin_client_creation_router
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.states.admin.client_management.client_creation_states import ClientCreationStates
from bot.utils.role import Role

ADMIN_TELEGRAM_ID = 100


class FakeUserRepo:
    def __init__(self, duplicates=None):
        self.duplicates = duplicates or {}
        self.created_users = []

    async def phone_exists(self, phone):
        return False

    async def create_user(self, user):
        self.created_users.append(user)

    async def get_clients_by_exact_name(self, full_name, clinic_id):
        return self.duplicates.get((full_name, clinic_id), [])


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=1)


class FakeClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=1, name="Зуб Мудрости", token="t")


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


@pytest.fixture
def fsm_context():
    storage = MemoryStorage()
    return FSMContext(storage=storage, key=(1, ADMIN_TELEGRAM_ID, ADMIN_TELEGRAM_ID))


async def _seed_data(fsm_context, full_name="Иванов Иван", phone="+998901234567"):
    await fsm_context.update_data(
        full_name=full_name, phone=phone, clinic_id=1, clinic_name="Зуб Мудрости",
    )


@pytest.mark.asyncio
async def test_finish_creates_directly_when_no_duplicate(fsm_context):
    user_repo = FakeUserRepo()
    router = create_admin_client_creation_router(user_repo, FakeStaffRepo(), FakeClinicRepo())
    finish = _find_handler(router, "client_creation_finish")

    await _seed_data(fsm_context)
    await finish(_callback_query(), fsm_context)

    assert len(user_repo.created_users) == 1
    assert user_repo.created_users[0].full_name == "Иванов Иван"


@pytest.mark.asyncio
async def test_finish_shows_warning_when_duplicate_found(fsm_context):
    duplicate = User(ID=5, full_name="Иванов Иван", phone="+998900000000", role=Role.CLIENT)
    user_repo = FakeUserRepo(duplicates={("Иванов Иван", 1): [duplicate]})
    router = create_admin_client_creation_router(user_repo, FakeStaffRepo(), FakeClinicRepo())
    finish = _find_handler(router, "client_creation_finish")

    await _seed_data(fsm_context)
    callback_query = _callback_query()
    await finish(callback_query, fsm_context)

    assert user_repo.created_users == []
    state = await fsm_context.get_state()
    assert state == ClientCreationStates.confirm_duplicate_name
    callback_query.message.edit_text.assert_called_once()
    text = callback_query.message.edit_text.call_args.args[0]
    assert "+998900000000" in text


@pytest.mark.asyncio
async def test_duplicate_confirm_creates_client(fsm_context):
    duplicate = User(ID=5, full_name="Иванов Иван", phone="+998900000000", role=Role.CLIENT)
    user_repo = FakeUserRepo(duplicates={("Иванов Иван", 1): [duplicate]})
    router = create_admin_client_creation_router(user_repo, FakeStaffRepo(), FakeClinicRepo())
    confirm = _find_handler(router, "client_creation_duplicate_confirm")

    await _seed_data(fsm_context)
    await fsm_context.set_state(ClientCreationStates.confirm_duplicate_name)

    await confirm(_callback_query(), fsm_context)

    assert len(user_repo.created_users) == 1
    assert user_repo.created_users[0].full_name == "Иванов Иван"


@pytest.mark.asyncio
async def test_duplicate_cancel_returns_to_confirm_create_without_creating(fsm_context):
    duplicate = User(ID=5, full_name="Иванов Иван", phone="+998900000000", role=Role.CLIENT)
    user_repo = FakeUserRepo(duplicates={("Иванов Иван", 1): [duplicate]})
    router = create_admin_client_creation_router(user_repo, FakeStaffRepo(), FakeClinicRepo())
    cancel = _find_handler(router, "client_creation_duplicate_cancel")

    await _seed_data(fsm_context)
    await fsm_context.set_state(ClientCreationStates.confirm_duplicate_name)

    callback_query = _callback_query()
    await cancel(callback_query, fsm_context)

    assert user_repo.created_users == []
    state = await fsm_context.get_state()
    assert state == ClientCreationStates.confirm_create
    callback_query.message.edit_text.assert_called_once()
    text = callback_query.message.edit_text.call_args.args[0]
    assert "Иванов Иван" in text
