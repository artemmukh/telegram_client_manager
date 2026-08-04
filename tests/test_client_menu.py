"""Handler-level tests for client_menu.py's text-triggered entrypoint.

Covers command wiring: /clients and /create_client used to funnel into the
client_managing choose-action menu; they now go straight to their own flows
(browse_clients_message in client_browser.py, create_client_name_message in
client_creation.py) and no longer match client_managing's filter. Only the
legacy "/client_managing" alias and the "👤 Управление клиентами"
reply-keyboard button text still route through client_managing.

Follows the direct-handler-call convention established in test_record_menu.py.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, User as TelegramUser

from bot.handlers.admin.client_management.client_browser import create_admin_client_browser_router
from bot.handlers.admin.client_management.client_creation import create_admin_client_creation_router
from bot.handlers.admin.client_management.client_menu import create_admin_client_menu_router
from bot.handlers.utils.admin_utils.input_helpers import ASK_FULL_NAME_PROMPT
from bot.keyboards.admin.client_management_kb.client_browser_kb import client_browser_search_kb
from bot.keyboards.admin.client_management_kb.client_creation_kb import client_creation_back_kb
from bot.keyboards.admin.client_management_kb.client_main_menu_kb import client_keyboard
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.states.admin.client_management.client_browser_states import ClientBrowserStates
from bot.utils.role import Role

ADMIN_TELEGRAM_ID = 999


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=1)


class FakeClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=1, name="Зуб Мудрости", token="t")


def _find_message_handler_object(router, name):
    for handler in router.message.handlers:
        if handler.callback.__name__ == name:
            return handler
    raise AssertionError(f"message handler {name} not found")


def _find_callback_handler_object(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler
    raise AssertionError(f"callback handler {name} not found")


def _current_user():
    return User(
        full_name="Админ Админов", phone="+998900000000", role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID, ID=1,
    )


def _callback_query():
    callback_query = MagicMock()
    # _begin_client_creation/_begin_client_browsing isinstance-branch on
    # CallbackQuery | Message; make this mock identify as a CallbackQuery so
    # it takes the edit_text branch instead of the Message/answer() one.
    callback_query.__class__ = CallbackQuery
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


# --- client_managing (text-triggered entrypoint: legacy alias + button text only) ---

@pytest.mark.asyncio
async def test_client_managing_filter_rejects_clients_and_create_client_commands():
    """/clients and /create_client no longer route through client_managing's
    choose-action menu -- only /client_managing and the legacy button text
    should still match this filter."""
    router = create_admin_client_menu_router()
    handler = _find_message_handler_object(router, "client_managing")

    accepted_texts = ("/client_managing", "👤 Управление клиентами")
    for text in accepted_texts:
        message = MagicMock()
        message.text = text
        matched, _ = await handler.check(message)
        assert matched is True, text

    rejected_texts = ("/clients", "/create_client", "some other text")
    for text in rejected_texts:
        message = MagicMock()
        message.text = text
        matched, _ = await handler.check(message)
        assert matched is False, text


@pytest.mark.asyncio
async def test_client_managing_still_answers_for_legacy_alias():
    """/client_managing (the only slash command left on this filter) must
    still show the choose-action menu."""
    router = create_admin_client_menu_router()
    client_managing = _find_message_handler_object(router, "client_managing").callback

    message = MagicMock()
    message.text = "/client_managing"
    message.answer = AsyncMock()

    await client_managing(message, _current_user())

    message.answer.assert_awaited_once_with(
        text="Выберите действие над клиентом:", reply_markup=client_keyboard()
    )


# --- /create_client goes straight to create_client_name_message ---

@pytest.mark.asyncio
async def test_create_client_name_message_triggers_same_flow_as_callback():
    """/create_client (create_client_name_message) must drive the exact same
    _begin_client_creation flow as the "➕ Создать клиента" callback
    (create_client_name)."""
    router = create_admin_client_creation_router(None, FakeStaffRepo(), FakeClinicRepo())
    create_client_name = _find_callback_handler_object(router, "create_client_name").callback
    create_client_name_message = _find_message_handler_object(router, "create_client_name_message").callback

    callback_query = _callback_query()
    state_cb = _fsm_context()
    await create_client_name(callback_query, state_cb, _current_user())

    message = MagicMock()
    message.from_user.id = ADMIN_TELEGRAM_ID
    message.answer = AsyncMock()
    state_msg = _fsm_context()
    await create_client_name_message(message, state_msg, _current_user())

    callback_query.message.edit_text.assert_awaited_once_with(
        ASK_FULL_NAME_PROMPT["ru"], reply_markup=client_creation_back_kb("ru"),
    )
    message.answer.assert_awaited_once_with(
        ASK_FULL_NAME_PROMPT["ru"], reply_markup=client_creation_back_kb("ru"),
    )

    assert await state_cb.get_state() == await state_msg.get_state()
    assert await state_cb.get_data() == await state_msg.get_data()


# --- /clients goes straight to browse_clients_message ---

@pytest.mark.asyncio
async def test_browse_clients_message_triggers_same_flow_as_callback():
    """/clients (browse_clients_message) must drive the exact same
    _begin_client_browsing flow as the "🔍 Найти клиента" callback
    (browse_clients)."""
    router = create_admin_client_browser_router(None, FakeStaffRepo(), FakeClinicRepo())
    browse_clients = _find_callback_handler_object(router, "browse_clients").callback
    browse_clients_message = _find_message_handler_object(router, "browse_clients_message").callback

    callback_query = _callback_query()
    state_cb = _fsm_context()
    await browse_clients(callback_query, state_cb, _current_user())

    message = MagicMock()
    message.from_user.id = ADMIN_TELEGRAM_ID
    message.answer = AsyncMock(return_value=MagicMock())
    state_msg = _fsm_context()
    await browse_clients_message(message, state_msg, _current_user())

    callback_query.message.edit_text.assert_awaited_once_with(
        "Выберите способ:", reply_markup=client_browser_search_kb("ru"),
    )
    message.answer.assert_awaited_once_with(
        "Выберите способ:", reply_markup=client_browser_search_kb("ru"),
    )

    assert await state_cb.get_state() == ClientBrowserStates.search_variant
    assert await state_msg.get_state() == ClientBrowserStates.search_variant
