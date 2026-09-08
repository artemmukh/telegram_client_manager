import logging
import math
import time
from collections import deque
from collections.abc import Callable

from aiogram import BaseMiddleware, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, TelegramObject

logger = logging.getLogger(__name__)

_MAX_ACTIONS = 15
_WINDOW_SECONDS = 30.0
_MESSAGES = {
    "ru": "Слишком много запросов. Попробуйте через {seconds} сек.",
    "uz": "Juda ko‘p so‘rov. {seconds} soniyadan keyin urinib ko‘ring.",
}


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[tuple[int, int], deque[float]] = {}
        self._last_notified: dict[tuple[int, int], float] = {}

    async def __call__(self, handler, event: TelegramObject, data: dict):
        key = self._key(event, data)
        if key is None:
            return await handler(event, data)

        now = self._clock()
        self._prune(now)
        timestamps = self._buckets.setdefault(key, deque())

        if len(timestamps) >= _MAX_ACTIONS:
            await self._reject(event, key, now, timestamps)
            return None

        timestamps.append(now)
        return await handler(event, data)

    @staticmethod
    def _key(event: TelegramObject, data: dict) -> tuple[int, int] | None:
        from_user = getattr(event, "from_user", None)
        bot = data.get("bot")
        bot_id = getattr(bot, "id", None)

        if from_user is None or from_user.is_bot or bot_id is None:
            return None

        return bot_id, from_user.id

    def _prune(self, now: float) -> None:
        cutoff = now - _WINDOW_SECONDS

        for key, timestamps in tuple(self._buckets.items()):
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if not timestamps:
                del self._buckets[key]

        for key, notified_at in tuple(self._last_notified.items()):
            if notified_at <= cutoff:
                del self._last_notified[key]

    async def _reject(
        self,
        event: TelegramObject,
        key: tuple[int, int],
        now: float,
        timestamps: deque[float],
    ) -> None:
        first_notice = now - self._last_notified.get(key, float("-inf")) >= _WINDOW_SECONDS
        if first_notice:
            self._last_notified[key] = now

        try:
            if isinstance(event, CallbackQuery):
                if first_notice:
                    await event.answer(self._text(event, timestamps[0], now))
                else:
                    await event.answer()
            elif first_notice:
                await event.answer(self._text(event, timestamps[0], now))
        except TelegramAPIError:
            logger.info("Unable to deliver throttling notification")

    @staticmethod
    def _text(event: TelegramObject, oldest_timestamp: float, now: float) -> str:
        language_code = getattr(getattr(event, "from_user", None), "language_code", None)
        language = "uz" if isinstance(language_code, str) and language_code.lower().startswith("uz") else "ru"
        seconds = max(1, math.ceil(oldest_timestamp + _WINDOW_SECONDS - now))
        return _MESSAGES[language].format(seconds=seconds)


def register_throttling(dispatcher: Dispatcher, instance: str) -> None:
    if instance != "zb":
        return

    middleware = ThrottlingMiddleware()
    dispatcher.message.outer_middleware(middleware)
    dispatcher.callback_query.outer_middleware(middleware)
