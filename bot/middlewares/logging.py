import logging
import time

from aiogram import BaseMiddleware

from bot.utils.observability import (
    bind_request_context,
    log_event,
    reset_request_context,
)

logger = logging.getLogger(__name__)
_SLOW_UPDATE_SECONDS = 1.0


def _update_kind(event: object) -> str:
    if hasattr(event, "callback_query") or event.__class__.__name__ == "CallbackQuery":
        return "callback_query"
    if hasattr(event, "message") or event.__class__.__name__ == "Message":
        return "message"
    return event.__class__.__name__.lower()


class LoggingMiddleware(BaseMiddleware):

    async def __call__(self, handler, event, data):
        start = time.perf_counter()
        context_token = bind_request_context()
        update_kind = _update_kind(event)

        try:
            log_event(logger, logging.DEBUG, "update_started", update_kind=update_kind)
            result = await handler(event, data)
            duration_ms = round((time.perf_counter() - start) * 1000)
            log_event(
                logger,
                logging.DEBUG,
                "update_completed",
                update_kind=update_kind,
                duration_ms=duration_ms,
            )
            if duration_ms >= _SLOW_UPDATE_SECONDS * 1000:
                log_event(
                    logger,
                    logging.WARNING,
                    "slow_update",
                    update_kind=update_kind,
                    duration_ms=duration_ms,
                )
            return result
        finally:
            reset_request_context(context_token)
