"""Unit tests for bot/middlewares/error.py::ErrorMiddleware.

There is no Dispatcher/aiogram wiring involved here: ErrorMiddleware.__call__
is invoked directly with a fake `handler` coroutine and a minimal
Message-/CallbackQuery-shaped fake event exposing an async `.answer(text)`.

This repo's Fake<Entity>Repository convention (tests/conftest.py,
.claude/skills/repo-test-fakes/SKILL.md) exists for repositories/services
backed by in-memory data, not for aiogram Message/CallbackQuery objects --
existing handler tests (test_appointment_booking_handler.py,
test_appointment_invite_handler.py) build those with
unittest.mock.MagicMock/AsyncMock instead, so these tests follow that same
established idiom rather than inventing a third convention.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.exceptions.exceptions import PaginationError
from bot.exceptions.user_exceptions import ValidationError
from bot.middlewares.error import ErrorMiddleware
from bot.models.user import User
from bot.utils.role import Role

LOGGER_NAME = "bot.middlewares.error"


def _client(language="uz"):
    return User(
        ID=1, full_name="Клиентов Клиент", phone="+998900000001", role=Role.CLIENT, language=language,
    )


def _make_message():
    """Minimal Message-shaped fake: only .answer is exercised by the middleware."""
    message = MagicMock()
    message.answer = AsyncMock()
    return message


def _make_callback_query():
    """Minimal CallbackQuery-shaped fake: only .answer is exercised by the middleware."""
    callback_query = MagicMock()
    callback_query.answer = AsyncMock()
    return callback_query


def _raising_handler(exc: Exception):
    async def handler(event, data):
        raise exc
    return handler


async def _call_middleware(handler, event, data=None):
    return await ErrorMiddleware().__call__(handler, event, data if data is not None else {})


@pytest.mark.asyncio
async def test_handler_success_passes_through_without_touching_answer():
    event = _make_message()

    async def handler(event, data):
        return "ok"

    result = await _call_middleware(handler, event)

    assert result == "ok"
    event.answer.assert_not_called()


@pytest.mark.asyncio
async def test_validation_error_answers_with_its_own_message_and_skips_other_branches(caplog):
    event = _make_message()
    handler = _raising_handler(ValidationError("Некорректный номер телефона"))

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        result = await _call_middleware(handler, event)

    assert result is None
    event.answer.assert_awaited_once_with("Некорректный номер телефона")
    assert "Unexpected" not in caplog.text
    assert "Unhandled exception" not in caplog.text


@pytest.mark.asyncio
async def test_bot_exception_answers_with_generic_message_and_logs_unexpected(caplog):
    event = _make_message()
    handler = _raising_handler(PaginationError("stale page"))

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        result = await _call_middleware(handler, event)

    assert result is None
    event.answer.assert_awaited_once_with("Произошла ошибка.")
    assert "Unexpected" in caplog.text
    assert "Unhandled exception" not in caplog.text


@pytest.mark.asyncio
async def test_bot_exception_uses_current_user_language_populated_by_inner_middleware(caplog):
    """current_user is only populated by UserContextMiddleware while running
    handler(event, data) (i.e. *inside* the try block), never before it, so
    the language resolution must read data after the handler ran, not at the
    top of __call__."""
    event = _make_message()

    async def handler(event, data):
        data["current_user"] = _client(language="uz")
        raise PaginationError("stale page")

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        result = await _call_middleware(handler, event)

    assert result is None
    event.answer.assert_awaited_once_with("Xatolik yuz berdi.")


@pytest.mark.asyncio
async def test_unhandled_exception_uses_current_user_language_populated_by_inner_middleware(caplog):
    event = _make_message()

    async def handler(event, data):
        data["current_user"] = _client(language="uz")
        raise TypeError("boom")

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        result = await _call_middleware(handler, event)

    assert result is None
    event.answer.assert_awaited_once_with("Xatolik yuz berdi, biz allaqachon buni hal qilmoqdamiz")


@pytest.mark.asyncio
async def test_generic_type_error_falls_back_to_unhandled_branch(caplog):
    event = _make_message()
    handler = _raising_handler(TypeError("boom"))

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        result = await _call_middleware(handler, event)

    assert result is None
    event.answer.assert_awaited_once_with("Произошла ошибка, мы уже разбираемся")
    assert "Unhandled exception" in caplog.text


@pytest.mark.asyncio
async def test_generic_key_error_also_falls_back_to_unhandled_branch(caplog):
    event = _make_message()
    handler = _raising_handler(KeyError("missing"))

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        result = await _call_middleware(handler, event)

    assert result is None
    event.answer.assert_awaited_once_with("Произошла ошибка, мы уже разбираемся")
    assert "Unhandled exception" in caplog.text


@pytest.mark.asyncio
async def test_answer_failure_on_unhandled_branch_is_swallowed_and_logged(caplog):
    """Simulates a stale callback: even .answer() itself raising must not
    escape __call__ -- the nested except logs and swallows it."""
    event = _make_message()
    event.answer = AsyncMock(side_effect=RuntimeError("stale callback"))
    handler = _raising_handler(ValueError("boom"))

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        result = await _call_middleware(handler, event)

    assert result is None
    event.answer.assert_awaited_once_with("Произошла ошибка, мы уже разбираемся")
    assert "Unhandled exception" in caplog.text
    assert "Failed to notify user about unhandled exception" in caplog.text


@pytest.mark.asyncio
async def test_callback_query_shaped_event_handles_unhandled_exception_same_as_message(caplog):
    event = _make_callback_query()
    handler = _raising_handler(TypeError("boom"))

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        result = await _call_middleware(handler, event)

    assert result is None
    event.answer.assert_awaited_once_with("Произошла ошибка, мы уже разбираемся")
    assert "Unhandled exception" in caplog.text


@pytest.mark.asyncio
async def test_message_and_callback_query_shaped_events_behave_identically_for_bot_exception(caplog):
    message_event = _make_message()
    callback_event = _make_callback_query()

    with caplog.at_level("ERROR", logger=LOGGER_NAME):
        await _call_middleware(_raising_handler(PaginationError("stale")), message_event)
        await _call_middleware(_raising_handler(PaginationError("stale")), callback_event)

    message_event.answer.assert_awaited_once_with("Произошла ошибка.")
    callback_event.answer.assert_awaited_once_with("Произошла ошибка.")
