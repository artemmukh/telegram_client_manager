"""Regression tests for the "restart appointment creation" button
(bot/handlers/admin/appointment_management/appointment_creation.py).

Covers two bugs fixed together:

Bug A: `restart_create` was registered with a `StateFilter` for
`AppointmentCreationStates.confirm_create`, but the "📝 Заполнить заново"
button is only ever shown from `AppointmentCreationStates.confirm`
(appointment_confirm_kb). Because aiogram's StateFilter requires an exact
match, the handler could never fire where the button is actually displayed.
The first test below exercises aiogram's real filter-check machinery
(FilterObject.call) to prove the handler matches at the state where the
button is shown - this would fail against the old, wrongly-state-filtered
registration.

Bug B: even if reachable, the old handler body never cleared FSM data, so
stale data from a previous fill-in attempt (client name, phone, datetime,
purpose, etc.) would leak into the restarted flow. The second set of tests
drives the real handler with a real FSMContext pre-seeded with stale data
and asserts only fresh keys survive.

Follows the direct-handler-call/fake-repository convention established in
test_appointment_creation_doctor_picker.py.
"""
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, User as TelegramUser

from bot.handlers.admin.appointment_management.appointment_creation import (
    create_admin_appointment_creation_router,
)
from bot.handlers.utils.admin_utils.appointment_calendar_helpers import format_month_label
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.states.admin.record_management.appointment_states import AppointmentCreationStates
from bot.utils.role import Role


ADMIN_TELEGRAM_ID = 999
FIXED_NOW = datetime(2026, 7, 6, 9, 0)


class FakeAppointmentRepository:
    async def create_appointment(self, appointment):
        return appointment


class FakeUserRepo:
    def __init__(self, admin=None, staff_by_clinic=None):
        self.admin = admin
        self.staff_by_clinic = staff_by_clinic or {}

    async def get_user_by_telegram_id(self, telegram_user_id):
        if self.admin and self.admin.telegram_user_id == telegram_user_id:
            return self.admin
        return None

    async def get_staff_users_by_clinic_id(self, clinic_id):
        return self.staff_by_clinic.get(clinic_id, [])


class FakeStaffRepo:
    def __init__(self, staff_by_telegram_id):
        self.staff_by_telegram_id = staff_by_telegram_id

    async def get_staff(self, telegram_user_id):
        return self.staff_by_telegram_id.get(telegram_user_id)

    async def get_staff_by_clinic_id(self, clinic_id):
        return [s for s in self.staff_by_telegram_id.values() if s.clinic_id == clinic_id]


class FakeClinicRepo:
    def __init__(self, clinic):
        self.clinic = clinic

    async def get_clinic_by_id(self, clinic_id):
        return self.clinic


def _admin(staff_id=42, telegram_user_id=ADMIN_TELEGRAM_ID, full_name="Artem Upravlyayuschiy"):
    return User(
        full_name=full_name,
        phone="+998900000000",
        role=Role.ADMIN,
        telegram_user_id=telegram_user_id,
        ID=staff_id,
        clinic_id=1,
        clinic_name="Zub Mudrosti",
    )


def _doctor(staff_id, telegram_user_id, full_name="Petrov Petr"):
    return User(
        full_name=full_name,
        phone="+998907654321",
        role=Role.ADMIN,
        telegram_user_id=telegram_user_id,
        ID=staff_id,
        clinic_id=1,
        clinic_name="Zub Mudrosti",
    )


def _build_router(user_repo, staff_repo):
    clinic_repo = FakeClinicRepo(Clinic(clinic_id=1, name="Zub Mudrosti", token="t"))
    return create_admin_appointment_creation_router(
        "zb", FakeAppointmentRepository(), user_repo, staff_repo, clinic_repo,
    )


def _find_callback_handler_object(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler
    raise AssertionError(f"callback handler {name} not found")


def _find_callback_handler(router, name):
    return _find_callback_handler_object(router, name).callback


def _callback_query(telegram_user_id=ADMIN_TELEGRAM_ID):
    callback_query = MagicMock()
    callback_query.from_user.id = telegram_user_id
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    callback_query.message.answer = AsyncMock()
    return callback_query


def _clinic_scope_router():
    admin = _admin()
    doctor = _doctor(99, 1000)
    user_repo = FakeUserRepo(admin=admin, staff_by_clinic={1: [admin, doctor]})
    staff_repo = FakeStaffRepo({
        ADMIN_TELEGRAM_ID: Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="clinic"),
        1000: Staff(telegram_user_id=1000, clinic_id=1, visibility_scope="own"),
    })
    return _build_router(user_repo, staff_repo)


def _own_scope_router():
    admin = _admin()
    user_repo = FakeUserRepo(admin=admin, staff_by_clinic={1: [admin]})
    staff_repo = FakeStaffRepo({
        ADMIN_TELEGRAM_ID: Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="own"),
    })
    return _build_router(user_repo, staff_repo)


# --- Bug A: the button must be reachable from AppointmentCreationStates.confirm ---

@pytest.mark.asyncio
async def test_restart_appointment_create_matches_at_confirm_state():
    """restart_create must fire when the bot is in AppointmentCreationStates.confirm
    (the only state from which the "📝 Заполнить заново" button is ever shown).

    This exercises aiogram's real FilterObject.call machinery rather than
    calling the handler function directly, so it would fail against the old
    registration that was filtered to AppointmentCreationStates.confirm_create.
    """
    router = _clinic_scope_router()
    handler = _find_callback_handler_object(router, "restart_create")

    event = MagicMock()
    event.data = "restart_appointment_create"

    for filter_object in handler.filters:
        result = await filter_object.call(event, raw_state=AppointmentCreationStates.confirm.state)
        assert result, f"filter {filter_object} rejected raw_state=confirm"


@pytest.mark.asyncio
async def test_restart_appointment_create_has_no_state_filter():
    """restart_create must not be gated to any single FSM state (in
    particular not confirm_create - a state that belongs to a different
    sub-flow and is unreachable from where this button is displayed).
    Only the F.data callback-data filter should remain."""
    router = _clinic_scope_router()
    handler = _find_callback_handler_object(router, "restart_create")

    from aiogram.fsm.state import State

    state_filters = [f for f in handler.filters if isinstance(f.callback, State)]
    assert state_filters == [], f"unexpected state filter(s) on restart_create: {state_filters}"


# --- Bug B: restarting must reset stale FSM data ---

def _stale_confirm_state_data():
    return {
        "clinic_name": "Old Clinic",
        "staff_options": {"1": "Old Doctor"},
        "full_name": "Старое Имя",
        "phone": "+998900000001",
        "appointment_datetime": "2026-01-01 10:00:00",
        "appointment_datetime_display": "1 января 2026, 10:00",
        "appointment_datetime_parsed": "stale-parsed-value",
        "purpose": "Старая цель визита",
    }


@pytest.mark.asyncio
async def test_restart_clears_stale_data_and_shows_doctor_picker_when_doctors_exist():
    router = _clinic_scope_router()
    restart_create = _find_callback_handler(router, "restart_create")

    storage = MemoryStorage()
    key = (Chat(id=100, type="private").id, TelegramUser(id=ADMIN_TELEGRAM_ID, is_bot=False, first_name="Admin").id)
    state = FSMContext(storage=storage, key=key)
    await state.set_state(AppointmentCreationStates.confirm)
    await state.update_data(**_stale_confirm_state_data())

    callback_query = _callback_query()
    await restart_create(callback_query, state, _admin())

    data = await state.get_data()
    assert data == {
        "clinic_name": "Zub Mudrosti",
        "staff_options": {"42": "Artem Upravlyayuschiy", "99": "Petrov Petr"},
    }
    assert await state.get_state() == AppointmentCreationStates.choose_doctor


@pytest.mark.asyncio
async def test_restart_clears_stale_data_and_goes_to_full_name_when_no_doctors():
    router = _own_scope_router()
    restart_create = _find_callback_handler(router, "restart_create")

    storage = MemoryStorage()
    key = (Chat(id=100, type="private").id, TelegramUser(id=ADMIN_TELEGRAM_ID, is_bot=False, first_name="Admin").id)
    state = FSMContext(storage=storage, key=key)
    await state.set_state(AppointmentCreationStates.confirm)
    await state.update_data(**_stale_confirm_state_data())

    callback_query = _callback_query()
    await restart_create(callback_query, state, _admin())

    data = await state.get_data()
    assert data == {"clinic_name": "Zub Mudrosti"}
    assert await state.get_state() == AppointmentCreationStates.client_full_name


# --- restart_create with client_preselected: booking-from-card flow re-enters without asking FIO ---

def _stale_preselected_own_scope_data():
    return {
        "clinic_name": "Old Clinic",
        "client_preselected": True,
        "full_name": "Иванов Иван",
        "phone": "+998901234567",
        "origin_client_id": 5,
        "origin_mode": "list",
        "origin_page": 2,
        "appointment_datetime": "2026-01-01 10:00:00",
        "purpose": "Старая цель визита",
    }


@pytest.mark.asyncio
async def test_restart_with_client_preselected_and_own_scope_restores_preselect_data_and_skips_full_name():
    """Own scope + client_preselected now (zb and mm both run "slots" mode)
    re-enters the calendar month view directly, instead of the retired
    free-text datetime prompt."""
    router = _own_scope_router()
    restart_create = _find_callback_handler(router, "restart_create")

    storage = MemoryStorage()
    key = (Chat(id=100, type="private").id, TelegramUser(id=ADMIN_TELEGRAM_ID, is_bot=False, first_name="Admin").id)
    state = FSMContext(storage=storage, key=key)
    await state.set_state(AppointmentCreationStates.confirm)
    await state.update_data(**_stale_preselected_own_scope_data())

    callback_query = _callback_query()
    with patch(
        "bot.handlers.utils.admin_utils.appointment_helpers.get_current_tashkent_datetime",
        return_value=FIXED_NOW,
    ):
        await restart_create(callback_query, state, _admin())

    data = await state.get_data()
    assert data == {
        "clinic_name": "Zub Mudrosti",
        "client_preselected": True,
        "full_name": "Иванов Иван",
        "phone": "+998901234567",
        "origin_client_id": 5,
        "origin_mode": "list",
        "origin_page": 2,
        "staff_user_id": 42,
        "calendar_year": FIXED_NOW.year,
        "calendar_month": FIXED_NOW.month,
    }
    assert await state.get_state() == AppointmentCreationStates.choose_day
    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == f"📅 {format_month_label(FIXED_NOW.year, FIXED_NOW.month)}"


@pytest.mark.asyncio
async def test_restart_with_client_preselected_and_clinic_scope_shows_doctor_picker_with_preselect_data():
    router = _clinic_scope_router()
    restart_create = _find_callback_handler(router, "restart_create")

    storage = MemoryStorage()
    key = (Chat(id=100, type="private").id, TelegramUser(id=ADMIN_TELEGRAM_ID, is_bot=False, first_name="Admin").id)
    state = FSMContext(storage=storage, key=key)
    await state.set_state(AppointmentCreationStates.confirm)
    await state.update_data(
        clinic_name="Old Clinic",
        client_preselected=True,
        full_name="Иванов Иван",
        phone="+998901234567",
        origin_client_id=5,
        origin_mode="search",
        origin_page=1,
        origin_search_data={"full_name": "Иванов"},
        appointment_datetime="2026-01-01 10:00:00",
        purpose="Старая цель визита",
    )

    callback_query = _callback_query()
    await restart_create(callback_query, state, _admin())

    data = await state.get_data()
    assert data == {
        "clinic_name": "Zub Mudrosti",
        "client_preselected": True,
        "full_name": "Иванов Иван",
        "phone": "+998901234567",
        "origin_client_id": 5,
        "origin_mode": "search",
        "origin_page": 1,
        "origin_search_data": {"full_name": "Иванов"},
        "staff_options": {"42": "Artem Upravlyayuschiy", "99": "Petrov Petr"},
    }
    assert await state.get_state() == AppointmentCreationStates.choose_doctor
