"""Handler-level tests for client_menu.py's text-triggered entrypoint.

Covers command wiring: the client_managing message handler now also matches
"/clients" and "/create_client" slash commands in addition to the legacy
"/client_managing" alias and the "👤 Управление клиентами" reply-keyboard
button text.

Follows the direct-handler-call convention established in test_record_menu.py.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.admin.client_management.client_menu import create_admin_client_menu_router
from bot.keyboards.admin.client_management_kb.client_main_menu_kb import client_keyboard
from bot.models.user import User
from bot.utils.role import Role


def _find_message_handler_object(router, name):
    for handler in router.message.handlers:
        if handler.callback.__name__ == name:
            return handler
    raise AssertionError(f"message handler {name} not found")


def _current_user():
    return User(full_name="Админ Админов", phone="+998900000000", role=Role.ADMIN, telegram_user_id=999, ID=1)


# --- client_managing (text-triggered entrypoint: buttons + slash commands) ---

@pytest.mark.asyncio
async def test_client_managing_filter_accepts_new_slash_commands_and_button_text():
    """Routing-level guard: F.text.in_({...}) must accept /client_managing,
    /clients, /create_client and the legacy button text, and reject unrelated
    text."""
    router = create_admin_client_menu_router()
    handler = _find_message_handler_object(router, "client_managing")

    accepted_texts = (
        "/client_managing", "/clients", "/create_client", "👤 Управление клиентами",
    )
    for text in accepted_texts:
        message = MagicMock()
        message.text = text
        matched, _ = await handler.check(message)
        assert matched is True, text

    message = MagicMock()
    message.text = "some other text"
    matched, _ = await handler.check(message)
    assert matched is False


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger_text", ["/clients", "/create_client"])
async def test_client_managing_new_slash_commands_trigger_same_response_as_button_text(trigger_text):
    """/clients and /create_client must trigger the exact same client_managing
    handler (and therefore the same response) as the pre-existing
    "👤 Управление клиентами" reply-keyboard button text."""
    router = create_admin_client_menu_router()
    client_managing = _find_message_handler_object(router, "client_managing").callback

    message = MagicMock()
    message.text = trigger_text
    message.answer = AsyncMock()

    await client_managing(message, _current_user())

    message.answer.assert_awaited_once_with(
        text="Выберите действие над клиентом:", reply_markup=client_keyboard()
    )
