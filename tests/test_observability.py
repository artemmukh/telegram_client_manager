import asyncio
import logging

import pytest

from bot.middlewares.error import ErrorMiddleware
from bot.middlewares.logging import LoggingMiddleware
from bot.utils.observability import (
    bind_request_context,
    get_request_id,
    log_event,
    reset_request_context,
)


def test_log_event_includes_request_id_and_forbids_sensitive_fields(caplog):
    logger = logging.getLogger("test.observability")
    token = bind_request_context("req-test")
    try:
        with caplog.at_level(logging.INFO, logger=logger.name):
            log_event(
                logger,
                logging.INFO,
                "booking_created",
                appointment_id=12,
                telegram_user_id=999,
                phone="+998000000000",
                complaint="private",
            )
    finally:
        reset_request_context(token)

    assert "event=booking_created" in caplog.text
    assert "request_id=req-test" in caplog.text
    assert "appointment_id=12" in caplog.text
    assert "999" not in caplog.text
    assert "+998000000000" not in caplog.text
    assert "private" not in caplog.text


def test_log_event_escapes_control_characters(caplog):
    logger = logging.getLogger("test.observability.escape")
    with caplog.at_level(logging.INFO, logger=logger.name):
        log_event(logger, logging.INFO, "event with newline", reason_code="line1\nline2")

    assert "reason_code=\"line1\\nline2\"" in caplog.text
    assert "line1\nline2" not in caplog.text


@pytest.mark.asyncio
async def test_request_context_isolated_and_reset_after_parallel_work():
    async def worker(request_id: str):
        token = bind_request_context(request_id)
        try:
            await asyncio.sleep(0)
            return get_request_id()
        finally:
            reset_request_context(token)

    assert await asyncio.gather(worker("req-a"), worker("req-b")) == ["req-a", "req-b"]
    assert get_request_id() is None


@pytest.mark.asyncio
async def test_logging_middleware_binds_context_for_handler_and_resets_afterward(caplog):
    event = type("Event", (), {"from_user": type("User", (), {"id": 123})()})()
    seen = []

    async def handler(event, data):
        seen.append(get_request_id())
        return "ok"

    with caplog.at_level(logging.DEBUG, logger="bot.middlewares.logging"):
        result = await LoggingMiddleware()(handler, event, {})

    assert result == "ok"
    assert len(seen) == 1 and seen[0]
    assert get_request_id() is None
    assert "event=update_started" in caplog.text
    assert "event=update_completed" in caplog.text
    assert "123" not in caplog.text


@pytest.mark.asyncio
async def test_logging_middleware_resets_context_after_handler_failure():
    event = type("Message", (), {})()

    async def handler(event, data):
        assert get_request_id() is not None
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await LoggingMiddleware()(handler, event, {})

    assert get_request_id() is None


@pytest.mark.asyncio
async def test_unexpected_error_keeps_exception_context_without_message_field(caplog):
    event = type("Message", (), {"answer": None})()

    async def answer(_text):
        return None

    event.answer = answer

    async def handler(_event, _data):
        raise RuntimeError("private input must not be a structured field")

    token = bind_request_context("req-error")
    try:
        with caplog.at_level(logging.ERROR, logger="bot.middlewares.error"):
            await ErrorMiddleware()(handler, event, {})
    finally:
        reset_request_context(token)

    record = next(record for record in caplog.records if "event=unexpected_error" in record.message)
    assert not record.exc_info
    assert "private input must not be a structured field" not in record.message
    assert "error_function=handler" in record.message
    assert "error_line=" in record.message
    assert "request_id=req-error" in record.message
