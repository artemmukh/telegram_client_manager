"""Handler-level tests for bot/handlers/common/start.py.

Regression coverage for the /start handler for already-registered clients:
show_main_client_menu requires (message, full_name, clinic_name), and
start_client previously called it with only 2 args, raising a TypeError.

Handlers are extracted directly from the router built by create_start_router,
mirroring the extraction pattern used in test_registration_handlers.py.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers.common.start import create_start_router
from bot.models.user import User
from bot.utils.role import Role


def _get_handler(observer, name):
    for handler in observer.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"Handler {name!r} not found")


@pytest.fixture
def memory_storage():
    return MemoryStorage()


@pytest.fixture
def fsm_context(memory_storage):
    return FSMContext(storage=memory_storage, key=(1, 1))


@pytest.fixture
def registered_client():
    return User(
        ID=1,
        full_name="Иван Иванов",
        phone="+998901234567",
        role=Role.CLIENT,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )


def _message():
    message = MagicMock()
    message.text = "/start"
    message.answer = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_start_client_sends_menu_with_clinic_name_without_raising(fsm_context, registered_client):
    router = create_start_router()
    start_client = _get_handler(router.message, "start_client")

    message = _message()

    await start_client(message, fsm_context, registered_client)

    assert message.answer.await_count == 2
    greeting_text = message.answer.call_args_list[0].args[0]
    assert registered_client.full_name in greeting_text
    assert registered_client.clinic_name in greeting_text


@pytest.mark.asyncio
async def test_start_client_clears_fsm_state(fsm_context, registered_client):
    router = create_start_router()
    start_client = _get_handler(router.message, "start_client")

    await fsm_context.set_state("some_state")
    await fsm_context.update_data(stale="data")

    await start_client(_message(), fsm_context, registered_client)

    assert await fsm_context.get_state() is None
    assert await fsm_context.get_data() == {}
