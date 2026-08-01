"""Dispatcher-level integration test for the Phase D calendar/slot-picker
refactor's routing safety net.

appointment_browser.py registers two read-only "browse by calendar" search
handlers for ApptCalendarMonthCB/ApptCalendarDayCB (scoped, via a
StateFilter, to AppointmentBrowserStates.calendar_month/calendar_day) plus
two new edit-datetime handlers for the same callback data classes (scoped to
AppointmentBrowserStates.edit_choose_day/edit_choose_slot). booking_requests.py
and reschedule_requests.py register their own state-filtered handlers for the
same callback data classes too (BookingNegotiationStates.choose_day/
choose_slot and the reschedule equivalent), and bot/run.py registers those
two routers before appointment_browser's so their negotiation flows take
priority while active.

Every other test in this suite calls handler functions directly, bypassing
aiogram's routing/filter-resolution layer entirely (see the repo-test-fakes
skill and e.g. test_appointment_browser_edit_datetime_calendar_slot_picker.py
/ test_booking_requests_calendar_slot_picker.py for that convention) so none
of them would catch a future router reorder, a typo in a state filter, or a
new AppointmentBrowserStates state silently misrouting one of these shared
callbacks. This file plugs that gap: it builds a real aiogram Dispatcher,
registers the actual routers built by the real create_admin_*_router
factories in the exact order bot/run.py uses, and drives them through
dp.feed_update() (with a fake Bot session so no real Telegram API calls
happen) so the real filter objects from the real routers decide which
handler fires.
"""
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Update
from aiogram.types import Message as TgMessage
from aiogram.types import User as TgUser

from bot.handlers.admin.appointment_management.appointment_browser import (
    create_admin_appointment_browser_router,
)
from bot.handlers.admin.appointment_management.appointment_creation import (
    create_admin_appointment_creation_router,
)
from bot.handlers.admin.appointment_management.booking_requests import (
    create_admin_booking_requests_router,
)
from bot.handlers.admin.appointment_management.reschedule_requests import (
    create_admin_reschedule_requests_router,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import ApptCalendarMonthCB
from bot.middlewares.user import UserContextMiddleware
from bot.models.user import User
from bot.states.admin.record_management.appointment_browser_states import AppointmentBrowserStates
from bot.states.admin.record_management.booking_negotiation_states import BookingNegotiationStates
from bot.utils.role import Role

ADMIN_TELEGRAM_ID = 999
CHAT_ID = 999
FAKE_BOT_TOKEN = "123456789:AAFakeTokenForCalendarRoutingTest00000"


class FakeSession(BaseSession):
    """Stands in for aiogram's real HTTP session so message.edit_text() /
    callback_query.answer() calls made by handlers under test do not hit the
    real Telegram API. Records every method sent so a test could additionally
    assert on the request payload, though the routing tests below only need
    to know that a request was made by the expected handler."""

    def __init__(self):
        super().__init__()
        self.requests: list = []

    async def close(self) -> None:
        pass

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        return True

    async def stream_content(self, *args, **kwargs):
        yield b""


class FakeUserRepo:
    """Shared user_repo instance: satisfies RoleFilter's dependency-injected
    user_exists/get_user_role checks (see bot/utils/role.py, injected via
    dp["user_repo"] exactly like bot/run.py does) as well as each router
    factory's own AppointmentManagement construction."""

    async def user_exists(self, telegram_user_id):
        return True

    async def get_user_role(self, telegram_user_id):
        return "admin"

    async def get_user_by_telegram_id(self, telegram_user_id):
        return User(
            ID=1, full_name="Админ Админов", phone="+998900000000", role=Role.ADMIN,
            telegram_user_id=telegram_user_id, clinic_id=1, clinic_name="Клиника",
        )

    async def get_client_by_id(self, user_id):
        return None


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return None


class FakeClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return None


class FakeAppointmentRepo:
    """None of the three routing scenarios below reach a repository call --
    every handler under test resolves purely from FSM state -- but each
    router factory still requires an appointment_repo positionally."""


def _spy(router, handler_name: str) -> AsyncMock:
    """Wrap a handler already registered on `router` with a passthrough
    AsyncMock spy, leaving its filters (state filter + callback-data filter)
    untouched, so tests can assert whether it fired without altering how
    aiogram picks it."""
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == handler_name:
            handler.callback = AsyncMock(side_effect=handler.callback)
            return handler.callback
    raise AssertionError(f"handler {handler_name!r} not registered on this router")


def _build_dispatcher(storage: MemoryStorage):
    user_repo = FakeUserRepo()
    staff_repo = FakeStaffRepo()
    clinic_repo = FakeClinicRepo()
    appointment_repo = FakeAppointmentRepo()

    creation_router = create_admin_appointment_creation_router(
        "zb", appointment_repo, user_repo, staff_repo, clinic_repo,
    )
    booking_router = create_admin_booking_requests_router(
        "zb", appointment_repo, user_repo, staff_repo, clinic_repo,
    )
    reschedule_router = create_admin_reschedule_requests_router(
        "zb", appointment_repo, user_repo, staff_repo, clinic_repo,
    )
    browser_router = create_admin_appointment_browser_router(
        "zb", appointment_repo, user_repo, staff_repo, clinic_repo,
    )

    dp = Dispatcher(storage=storage)
    dp["user_repo"] = user_repo
    dp.callback_query.middleware(UserContextMiddleware(user_repo))

    # Mirrors bot/run.py's registration order exactly: appointment_creation
    # first, then booking_requests/reschedule_requests (whose choose_day/
    # choose_slot calendar handlers must win over appointment_browser's own
    # calendar handlers while a negotiation state is active), then
    # appointment_browser last.
    dp.include_router(creation_router)
    dp.include_router(booking_router)
    dp.include_router(reschedule_router)
    dp.include_router(browser_router)

    return dp, {
        "creation": creation_router,
        "booking": booking_router,
        "reschedule": reschedule_router,
        "browser": browser_router,
    }


def _calendar_month_update(update_id: int) -> Update:
    chat = Chat(id=CHAT_ID, type="private")
    message = TgMessage(message_id=1, date=datetime.now(), chat=chat)
    from_user = TgUser(id=ADMIN_TELEGRAM_ID, is_bot=False, first_name="Admin")
    callback_query = CallbackQuery(
        id=str(update_id), from_user=from_user, chat_instance="1", message=message,
        data=ApptCalendarMonthCB(year=2026, month=8).pack(),
    )
    return Update(update_id=update_id, callback_query=callback_query)


@pytest.fixture
def fake_bot():
    return Bot(token=FAKE_BOT_TOKEN, session=FakeSession())


async def _seed_state(bot: Bot, storage: MemoryStorage, state_value, data: dict) -> None:
    key = StorageKey(bot_id=bot.id, chat_id=CHAT_ID, user_id=ADMIN_TELEGRAM_ID)
    fsm = FSMContext(storage=storage, key=key)
    await fsm.set_state(state_value)
    await fsm.update_data(**data)


@pytest.mark.asyncio
async def test_calendar_month_in_browser_search_state_routes_to_browsers_own_handler(fake_bot):
    storage = MemoryStorage()
    dp, routers = _build_dispatcher(storage)

    browser_search_spy = _spy(routers["browser"], "change_calendar_month")
    browser_edit_spy = _spy(routers["browser"], "change_edit_datetime_calendar_month")
    booking_propose_spy = _spy(routers["booking"], "change_propose_calendar_month")

    await _seed_state(fake_bot, storage, AppointmentBrowserStates.calendar_month, {})

    await dp.feed_update(bot=fake_bot, update=_calendar_month_update(1))

    browser_search_spy.assert_awaited_once()
    browser_edit_spy.assert_not_awaited()
    booking_propose_spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_calendar_month_in_edit_datetime_state_routes_to_edit_datetime_handler(fake_bot):
    storage = MemoryStorage()
    dp, routers = _build_dispatcher(storage)

    browser_search_spy = _spy(routers["browser"], "change_calendar_month")
    browser_edit_spy = _spy(routers["browser"], "change_edit_datetime_calendar_month")
    booking_propose_spy = _spy(routers["booking"], "change_propose_calendar_month")

    await _seed_state(
        fake_bot, storage, AppointmentBrowserStates.edit_choose_day,
        {"appointment_id": 1, "mode": "list", "page": 1},
    )

    await dp.feed_update(bot=fake_bot, update=_calendar_month_update(2))

    browser_edit_spy.assert_awaited_once()
    browser_search_spy.assert_not_awaited()
    booking_propose_spy.assert_not_awaited()


@pytest.mark.asyncio
async def test_calendar_month_in_booking_negotiation_state_does_not_leak_into_browser_router(fake_bot):
    storage = MemoryStorage()
    dp, routers = _build_dispatcher(storage)

    browser_search_spy = _spy(routers["browser"], "change_calendar_month")
    browser_edit_spy = _spy(routers["browser"], "change_edit_datetime_calendar_month")
    booking_propose_spy = _spy(routers["booking"], "change_propose_calendar_month")

    await _seed_state(
        fake_bot, storage, BookingNegotiationStates.choose_day, {"appointment_id": 1},
    )

    await dp.feed_update(bot=fake_bot, update=_calendar_month_update(3))

    booking_propose_spy.assert_awaited_once()
    browser_search_spy.assert_not_awaited()
    browser_edit_spy.assert_not_awaited()

