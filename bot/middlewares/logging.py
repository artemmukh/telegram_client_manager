from aiogram import BaseMiddleware
import logging
import time

class LoggingMiddleware(BaseMiddleware):

    async def __call__(self, handler, event, data):
        logger = logging.getLogger(__name__)
        start = time.perf_counter()



        logger.info("Update from %s", event.from_user.id)

        result = await handler(event, data)

        logger.info(
            "Handled in %.3f",
            time.perf_counter() - start
        )

        return result