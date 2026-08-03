import logging

from aiogram import BaseMiddleware

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError

_GENERIC_ERROR_TEXT = {
    "ru": "Произошла ошибка.",
    "uz": "Xatolik yuz berdi.",
}

_UNHANDLED_ERROR_TEXT = {
    "ru": "Произошла ошибка, мы уже разбираемся",
    "uz": "Xatolik yuz berdi, biz allaqachon buni hal qilmoqdamiz",
}


class ErrorMiddleware(BaseMiddleware):

    @staticmethod
    def _lang(data: dict) -> str:
        """current_user is populated by UserContextMiddleware, which runs
        *inside* this middleware's handler() call, so it is only available
        after the try block runs -- never at the top of __call__."""
        current_user = data.get("current_user")
        return current_user.language if current_user else "ru"

    async def __call__(self, handler, event, data):

        logger = logging.getLogger(__name__)

        try:
            return await handler(event, data)

        except ValidationError as e:
            await event.answer(e.localized(self._lang(data)))

        except BotException:
            logger.exception("Unexpected")
            lang = self._lang(data)
            await event.answer(_GENERIC_ERROR_TEXT.get(lang, _GENERIC_ERROR_TEXT["ru"]))

        except Exception:
            logger.exception("Unhandled exception")
            try:
                lang = self._lang(data)
                await event.answer(_UNHANDLED_ERROR_TEXT.get(lang, _UNHANDLED_ERROR_TEXT["ru"]))
            except Exception:
                logger.exception("Failed to notify user about unhandled exception")