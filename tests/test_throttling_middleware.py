import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.middlewares.throttling import ThrottlingMiddleware, register_throttling

BOT_TOKEN = "123456789:AAFakeTokenForThrottlingTests00000"
SECOND_BOT_TOKEN = "987654321:AAFakeTokenForThrottlingTests00000"


class RecordingSession(BaseSession):
    """Keeps Telegram answer requests local while exercising real aiogram objects."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[object] = []
        self.fail_next_request = False

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method, timeout=None):
        self.requests.append(method)
        if self.fail_next_request:
            self.fail_next_request = False
            raise TelegramBadRequest(method, "Bad Request: stale update")
        return True

    async def stream_content(self, *args, **kwargs):
        yield b""


@dataclass
class Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


class CountingMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, handler, event, data):
        self.calls += 1
        return await handler(event, data)


def _user(*, user_id: int = 1, is_bot: bool = False, language_code: str | None = None) -> User:
    return User(id=user_id, is_bot=is_bot, first_name="User", language_code=language_code)


def _message(
    bot: Bot,
    *,
    user_id: int = 1,
    is_bot: bool = False,
    with_user: bool = True,
    language_code: str | None = None,
) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(timezone.utc),
        chat=Chat(id=user_id, type="private"),
        from_user=_user(user_id=user_id, is_bot=is_bot, language_code=language_code) if with_user else None,
        text="test",
    ).as_(bot)


def _callback(bot: Bot, *, user_id: int = 1, language_code: str | None = None) -> CallbackQuery:
    return CallbackQuery(
        id="callback-id",
        from_user=_user(user_id=user_id, language_code=language_code),
        chat_instance="chat-instance",
        data="action",
    ).as_(bot)


async def _call(
    middleware: ThrottlingMiddleware,
    event: Message | CallbackQuery,
    bot: Bot,
    accepted: list[object],
) -> object:
    async def handler(event, data):
        accepted.append(event)
        return "handled"

    return await middleware(handler, event, {"bot": bot})


@pytest.fixture
def bot() -> Bot:
    return Bot(token=BOT_TOKEN, session=RecordingSession())


@pytest.mark.asyncio
async def test_sixteenth_action_is_stopped_after_fifteen_accepted_actions(bot: Bot) -> None:
    """Catches a missing or off-by-one admission check."""
    clock = Clock()
    middleware = ThrottlingMiddleware(clock=clock)
    accepted: list[object] = []

    for second in range(15):
        clock.now = second
        assert await _call(middleware, _message(bot), bot, accepted) == "handled"

    clock.now = 14
    assert await _call(middleware, _message(bot), bot, accepted) is None

    assert len(accepted) == 15
    request = bot.session.requests[-1]
    assert request.text == "Слишком много запросов. Попробуйте через 16 сек."


@pytest.mark.asyncio
async def test_window_reopens_at_thirty_seconds_and_rejected_attempts_do_not_extend_it(bot: Bot) -> None:
    """Catches a cooldown reset based on rejected attempts instead of accepted actions."""
    clock = Clock()
    middleware = ThrottlingMiddleware(clock=clock)
    accepted: list[object] = []

    for second in range(15):
        clock.now = second
        await _call(middleware, _message(bot), bot, accepted)

    clock.now = 29
    await _call(middleware, _message(bot), bot, accepted)
    clock.now = 30
    assert await _call(middleware, _message(bot), bot, accepted) == "handled"

    assert len(accepted) == 16


@pytest.mark.asyncio
async def test_messages_and_callbacks_share_one_limit_and_callbacks_are_always_answered(bot: Bot) -> None:
    """Catches separate counters or a callback spinner left unresolved."""
    clock = Clock()
    middleware = ThrottlingMiddleware(clock=clock)
    accepted: list[object] = []

    for _ in range(14):
        await _call(middleware, _message(bot, language_code="uz"), bot, accepted)
    await _call(middleware, _callback(bot, language_code="uz"), bot, accepted)

    clock.now = 1
    await _call(middleware, _callback(bot, language_code="uz"), bot, accepted)
    clock.now = 2
    await _call(middleware, _callback(bot, language_code="uz"), bot, accepted)

    assert len(accepted) == 15
    first_rejection, second_rejection = bot.session.requests[-2:]
    assert first_rejection.text == "Juda ko‘p so‘rov. 29 soniyadan keyin urinib ko‘ring."
    assert second_rejection.text is None


@pytest.mark.asyncio
async def test_limit_is_independent_for_users_and_bots(bot: Bot) -> None:
    """Catches a key that omits either the Telegram user or bot identity."""
    clock = Clock()
    middleware = ThrottlingMiddleware(clock=clock)
    accepted: list[object] = []
    second_bot = Bot(token=SECOND_BOT_TOKEN, session=RecordingSession())

    for _ in range(15):
        await _call(middleware, _message(bot, user_id=1), bot, accepted)

    assert await _call(middleware, _message(bot, user_id=2), bot, accepted) == "handled"
    assert await _call(middleware, _message(second_bot, user_id=1), second_bot, accepted) == "handled"
    assert len(accepted) == 17


@pytest.mark.asyncio
async def test_events_without_a_human_sender_are_not_limited(bot: Bot) -> None:
    """Catches accidental throttling of channel-style or bot-originated events."""
    middleware = ThrottlingMiddleware(clock=Clock())
    accepted: list[object] = []

    for _ in range(6):
        assert await _call(middleware, _message(bot, with_user=False), bot, accepted) == "handled"
        assert await _call(middleware, _message(bot, is_bot=True), bot, accepted) == "handled"

    assert len(accepted) == 12
    assert bot.session.requests == []


@pytest.mark.asyncio
async def test_concurrent_actions_cannot_bypass_the_limit(bot: Bot) -> None:
    """Catches an admission check that yields before recording an accepted action."""
    middleware = ThrottlingMiddleware(clock=Clock())
    accepted: list[object] = []

    async def handler(event, data):
        accepted.append(event)
        await asyncio.sleep(0)

    await asyncio.gather(
        *(middleware(handler, _message(bot), {"bot": bot}) for _ in range(16)),
    )

    assert len(accepted) == 15


@pytest.mark.asyncio
async def test_accepted_action_still_counts_when_downstream_handler_fails(bot: Bot) -> None:
    """Catches quota accounting deferred until after the business handler returns."""
    middleware = ThrottlingMiddleware(clock=Clock())
    accepted: list[object] = []

    async def failing_handler(event, data):
        accepted.append(event)
        raise ValueError("handler failed")

    with pytest.raises(ValueError, match="handler failed"):
        await middleware(failing_handler, _message(bot), {"bot": bot})

    for _ in range(14):
        await _call(middleware, _message(bot), bot, accepted)
    await _call(middleware, _message(bot), bot, accepted)

    assert len(accepted) == 15


@pytest.mark.asyncio
async def test_telegram_error_while_notifying_a_rejected_action_is_swallowed(bot: Bot) -> None:
    """Catches a stale Telegram response turning rate limiting into a failed update."""
    middleware = ThrottlingMiddleware(clock=Clock())
    accepted: list[object] = []

    for _ in range(15):
        await _call(middleware, _message(bot), bot, accepted)

    bot.session.fail_next_request = True
    assert await _call(middleware, _message(bot), bot, accepted) is None
    assert len(accepted) == 15


@pytest.mark.asyncio
async def test_registered_zb_limiter_runs_before_inner_middlewares_and_mm_has_no_limiter() -> None:
    """Catches missing ZB wiring, a late hook, or an accidental MM rollout."""
    zb_bot = Bot(token=BOT_TOKEN, session=RecordingSession())
    zb_dispatcher = Dispatcher()
    register_throttling(zb_dispatcher, "zb")
    inner = CountingMiddleware()
    zb_dispatcher.message.middleware(inner)
    handled: list[Message] = []

    @zb_dispatcher.message()
    async def handle_message(message: Message) -> None:
        handled.append(message)

    for update_id in range(16):
        update = Update(update_id=update_id, message=_message(zb_bot))
        await zb_dispatcher.feed_update(zb_bot, update)

    assert len(handled) == 15
    assert inner.calls == 15

    mm_bot = Bot(token=SECOND_BOT_TOKEN, session=RecordingSession())
    mm_dispatcher = Dispatcher()
    register_throttling(mm_dispatcher, "mm")
    mm_handled: list[Message] = []

    @mm_dispatcher.message()
    async def handle_mm_message(message: Message) -> None:
        mm_handled.append(message)

    for update_id in range(6):
        update = Update(update_id=update_id, message=_message(mm_bot))
        await mm_dispatcher.feed_update(mm_bot, update)

    assert len(mm_handled) == 6
