"""Handler-level tests for record_menu.py's "back_to_main_records" callback.

Covers the "booking from a client's card" follow-up behaviour: when the
appointment-creation flow was entered via a client's card (client_preselected
in FSM data), cancelling/returning must land back on that client's card
(restoring search_data if the card was opened via search) instead of the
generic records menu. Also covers the just-added regression fix: if the
origin client was deleted in the meantime, render_client_card returns False
and back_to_main must fall back to editing the message into the generic
records menu rather than leaving it unedited.

Follows the direct-handler-call/fake-repository convention established in
test_appointment_creation_doctor_picker.py / test_appointment_creation_restart.py.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, User as TelegramUser

from bot.handlers.admin.appointment_management.record_menu import create_admin_record_router
from bot.handlers.utils.admin_utils.client_browser_helpers import build_client_card_text
from bot.keyboards.admin.client_management_kb.client_browser_kb import client_card_kb
from bot.keyboards.admin.record_management_kb.record_main_menu_kb import record_keyboard
from bot.models.user import User
from bot.utils.role import Role


ADMIN_TELEGRAM_ID = 999


class FakeUserRepoForRecordMenu:
    def __init__(self, clients_by_id=None):
        self.clients_by_id = dict(clients_by_id or {})

    async def get_client_by_id(self, user_id):
        return self.clients_by_id.get(user_id)


class FakeStaffRepo:
    pass


class FakeClinicRepo:
    pass


def _find_callback_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"callback handler {name} not found")


def _callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _fsm_context():
    storage = MemoryStorage()
    key = (
        Chat(id=100, type="private").id,
        TelegramUser(id=ADMIN_TELEGRAM_ID, is_bot=False, first_name="Admin").id,
    )
    return FSMContext(storage=storage, key=key)


def _build_router(clients_by_id=None):
    user_repo = FakeUserRepoForRecordMenu(clients_by_id=clients_by_id)
    return create_admin_record_router(user_repo, FakeStaffRepo(), FakeClinicRepo())


# --- back_to_main with client_preselected: returns to the origin client's card ---

@pytest.mark.asyncio
async def test_back_to_main_with_client_preselected_renders_origin_card_and_restores_search_data():
    client = User(ID=5, full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, clinic_id=1)
    router = _build_router(clients_by_id={5: client})
    back_to_main = _find_callback_handler(router, "back_to_main")

    state = _fsm_context()
    await state.update_data(
        client_preselected=True,
        full_name="Иванов Иван",
        phone="+998901234567",
        origin_client_id=5,
        origin_mode="search",
        origin_page=1,
        origin_search_data={"full_name": "Иванов"},
        staff_options={"42": "Врач"},
    )

    callback_query = _callback_query()
    await back_to_main(callback_query, state)

    data = await state.get_data()
    assert data.get("search_data") == {"full_name": "Иванов"}
    assert "client_preselected" not in data
    assert "origin_client_id" not in data
    assert "staff_options" not in data

    callback_query.answer.assert_awaited_once_with('')
    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == build_client_card_text(client)
    assert kwargs["reply_markup"] == client_card_kb(5, "search", 1)


@pytest.mark.asyncio
async def test_back_to_main_with_client_preselected_and_no_origin_search_data_does_not_set_search_data():
    client = User(ID=5, full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, clinic_id=1)
    router = _build_router(clients_by_id={5: client})
    back_to_main = _find_callback_handler(router, "back_to_main")

    state = _fsm_context()
    await state.update_data(
        client_preselected=True,
        full_name="Иванов Иван",
        phone="+998901234567",
        origin_client_id=5,
        origin_mode="list",
        origin_page=1,
    )

    callback_query = _callback_query()
    await back_to_main(callback_query, state)

    data = await state.get_data()
    assert "search_data" not in data
    callback_query.message.edit_text.assert_awaited_once()


# --- Regression: origin client deleted -> falls back to generic records menu ---

@pytest.mark.asyncio
async def test_back_to_main_falls_back_to_generic_menu_when_origin_client_deleted():
    router = _build_router(clients_by_id={})
    back_to_main = _find_callback_handler(router, "back_to_main")

    state = _fsm_context()
    await state.update_data(
        client_preselected=True,
        full_name="Иванов Иван",
        phone="+998901234567",
        origin_client_id=5,
        origin_mode="list",
        origin_page=1,
    )

    callback_query = _callback_query()
    await back_to_main(callback_query, state)

    callback_query.answer.assert_awaited_once_with("Клиент не найден.", show_alert=True)
    callback_query.message.edit_text.assert_awaited_once_with(
        "Выберите действие над записью:",
        reply_markup=record_keyboard(),
    )


# --- Regression check: client_preselected falsy/absent keeps original behaviour ---

@pytest.mark.asyncio
async def test_back_to_main_without_client_preselected_shows_generic_menu_unchanged():
    router = _build_router()
    back_to_main = _find_callback_handler(router, "back_to_main")

    state = _fsm_context()
    await state.update_data(some_unrelated_key="value")

    callback_query = _callback_query()
    await back_to_main(callback_query, state)

    data = await state.get_data()
    assert data == {}

    callback_query.answer.assert_awaited_once_with('')
    callback_query.message.edit_text.assert_awaited_once_with(
        "Выберите действие над записью:",
        reply_markup=record_keyboard(),
    )
