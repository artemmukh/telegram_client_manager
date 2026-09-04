import logging
import traceback

from aiogram import BaseMiddleware

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError
from bot.utils.observability import log_event

_GENERIC_ERROR_TEXT = {
    "ru": "Произошла ошибка.",
    "uz": "Xatolik yuz berdi.",
}

_UNHANDLED_ERROR_TEXT = {
    "ru": "Произошла ошибка, мы уже разбираемся",
    "uz": "Xatolik yuz berdi, biz allaqachon buni hal qilmoqdamiz",
}

logger = logging.getLogger(__name__)


def _safe_error_location(error: BaseException) -> dict[str, str | int]:
    frames = traceback.extract_tb(error.__traceback__) if error.__traceback__ else ()
    if not frames:
        return {}
    frame = frames[-1]
    return {"error_function": frame.name, "error_line": frame.lineno}


class ErrorMiddleware(BaseMiddleware):

    @staticmethod
    def _lang(data: dict) -> str:
        """current_user is populated by UserContextMiddleware, which runs
        *inside* this middleware's handler() call, so it is only available
        after the try block runs -- never at the top of __call__."""
        current_user = data.get("current_user")
        return current_user.language if current_user else "ru"

    async def __call__(self, handler, event, data):

        try:
            return await handler(event, data)

        except ValidationError as e:
            await event.answer(e.localized(self._lang(data)))

        except BotException as e:
            log_event(logger, logging.INFO, "domain_error_handled", error_type=type(e).__name__)
            lang = self._lang(data)
            await event.answer(_GENERIC_ERROR_TEXT.get(lang, _GENERIC_ERROR_TEXT["ru"]))

        except Exception as e:  # noqa: BLE001 - final middleware boundary
            log_event(
                logger,
                logging.ERROR,
                "unexpected_error",
                error_type=type(e).__name__,
                **_safe_error_location(e),
            )
            try:
                lang = self._lang(data)
                await event.answer(_UNHANDLED_ERROR_TEXT.get(lang, _UNHANDLED_ERROR_TEXT["ru"]))
            except Exception as error:  # noqa: BLE001 - error response must not escape middleware
                log_event(
                    logger,
                    logging.ERROR,
                    "user_error_delivery_failed",
                    error_type="answer_failed",
                    **_safe_error_location(error),
                )
