"""Handler-level tests for the help router (bot/handlers/common/help.py).

Handlers are extracted directly from the router built by create_help_router,
mirroring the extraction pattern used in test_registration_handlers.py.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.common.help import create_help_router


def _get_handler(observer, name):
    for handler in observer.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"Handler {name!r} not found")


def _get_handler_object(observer, name):
    for handler in observer.handlers:
        if handler.callback.__name__ == name:
            return handler
    raise AssertionError(f"Handler {name!r} not found")


def _magic_filter(handler_object):
    for filter_object in handler_object.filters:
        if filter_object.magic is not None:
            return filter_object.magic
    raise AssertionError("No magic filter found on handler")


def _message(text=None):
    message = MagicMock()
    message.text = text
    message.from_user.id = 999
    message.answer = AsyncMock()
    return message


def _callback(data=None):
    callback = MagicMock()
    callback.data = data
    callback.from_user.id = 999
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()
    return callback


def test_help_client_triggers_on_slash_help():
    router = create_help_router()
    handler_object = _get_handler_object(router.message, "help_client")
    magic = _magic_filter(handler_object)

    assert magic.resolve(_message(text="/help")) is True


def test_help_client_triggers_on_new_pomoshch_label():
    router = create_help_router()
    handler_object = _get_handler_object(router.message, "help_client")
    magic = _magic_filter(handler_object)

    assert magic.resolve(_message(text="❓ Помощь")) is True


def test_help_client_does_not_trigger_on_old_spravka_label():
    router = create_help_router()
    handler_object = _get_handler_object(router.message, "help_client")
    magic = _magic_filter(handler_object)

    assert magic.resolve(_message(text="❓ Справка")) is False


def test_help_admin_still_triggers_on_spravka_label():
    router = create_help_router()
    handler_object = _get_handler_object(router.message, "help_admin")
    magic = _magic_filter(handler_object)

    assert magic.resolve(_message(text="❓ Справка")) is True


def test_help_admin_triggers_on_slash_help():
    router = create_help_router()
    handler_object = _get_handler_object(router.message, "help_admin")
    magic = _magic_filter(handler_object)

    assert magic.resolve(_message(text="/help")) is True


@pytest.mark.asyncio
async def test_client_help_guide_callback_sends_all_six_steps_in_order():
    router = create_help_router()
    help_client_guide = _get_handler(router.callback_query, "help_client_guide")

    callback = _callback(data="client_help_guide")

    await help_client_guide(callback)

    callback.message.edit_text.assert_awaited_once()
    sent_text = callback.message.edit_text.call_args.args[0]

    steps = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]
    for step in steps:
        assert step in sent_text

    step_positions = [sent_text.index(step) for step in steps]
    assert step_positions == sorted(step_positions)

    callback.answer.assert_awaited_once()
