"""Handler-level tests for the profile-initiated name-change request flow
(bot/handlers/client/name_change_request.py)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers.client.name_change_request import create_name_change_request_router
from bot.models.user import User
from bot.states.name_change_states import NameChangeStates
from bot.utils.role import Role


class FakeClientManagement:
    def __init__(self, user: User):
        self.user = user
        self.requested_changes = []

    async def request_name_change(self, user_id, new_full_name):
        self.requested_changes.append((user_id, new_full_name))
        self.user.pending_full_name = new_full_name
        return self.user


class FakeClientNotificationService:
    def __init__(self):
        self.name_change_requests = []

    async def notify_admins_name_change_request(self, user, new_full_name, reply_markup):
        self.name_change_requests.append((user, new_full_name, reply_markup))


def _get_handler(observer, name):
    for handler in observer.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"Handler {name!r} not found")


@pytest.fixture
def current_user():
    return User(
        ID=7,
        full_name="Иван Иванов",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=555,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )


@pytest.fixture
def fsm_context():
    return FSMContext(storage=MemoryStorage(), key=(1, 1))


@pytest.fixture
def client_management(current_user):
    return FakeClientManagement(current_user)


@pytest.fixture
def notification_service():
    return FakeClientNotificationService()


@pytest.fixture
def router(client_management, notification_service):
    return create_name_change_request_router(client_management, notification_service)


def _callback():
    callback = MagicMock()
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()
    return callback


def _message(text):
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_start_name_change_sets_entering_name_state(router, fsm_context):
    start_name_change = _get_handler(router.callback_query, "start_name_change")

    await start_name_change(_callback(), fsm_context)

    assert await fsm_context.get_state() == NameChangeStates.entering_name


@pytest.mark.asyncio
async def test_process_name_change_submits_request_and_notifies_admins(
    router, fsm_context, client_management, notification_service, current_user,
):
    process_name_change = _get_handler(router.message, "process_name_change")

    await fsm_context.set_state(NameChangeStates.entering_name)
    message = _message("Петр Петров")

    await process_name_change(message, fsm_context, current_user=current_user)

    assert client_management.requested_changes == [(current_user.ID, "Петр Петров")]
    assert len(notification_service.name_change_requests) == 1

    notified_user, new_full_name, reply_markup = notification_service.name_change_requests[0]
    assert notified_user is current_user
    assert new_full_name == "Петр Петров"
    assert reply_markup is not None

    assert await fsm_context.get_state() is None
    message.answer.assert_awaited_once()

