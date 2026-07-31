import logging

from aiogram import BaseMiddleware

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError


class ErrorMiddleware(BaseMiddleware):

    async def __call__(self, handler, event, data):

        logger = logging.getLogger(__name__)

        try:
            return await handler(event, data)

        except ValidationError as e:
            await event.answer(str(e))

        except BotException:
            logger.exception("Unexpected")
            await event.answer("Произошла ошибка.")

        except Exception:
            logger.exception("Unhandled exception")
            try:
                await event.answer("Произошла ошибка, мы уже разбираемся")
            except Exception:
                logger.exception("Failed to notify user about unhandled exception")