import pytest
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import CallbackQuery

from bot.handlers.admin.appointment_management.appointment_browser import (
    create_admin_appointment_browser_router,
)
from bot.handlers.utils.admin_utils.appointment_calendar_helpers import (
    CALENDAR_MAX_YEAR,
    clamp_month_to_range,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import (
    ApptActionCB,
    ApptCalendarDayCB,
    ApptCalendarMonthCB,
    ApptCardCB,
    ApptPageCB,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_kb import (
    appointment_calendar_kb,
    appointment_list_kb,
)
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.services.utils.date_parser import get_current_tashkent_datetime
from bot.states.admin.record_management.appointment_browser_states import AppointmentBrowserStates
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


OWN_ADMIN_TELEGRAM_ID = 999
CLINIC_ADMIN_TELEGRAM_ID = 2000


class FakeState:
    """Dict-backed stand-in for FSMContext.

    Unlike the static MagicMock(_state(**data)) used in the ownership/
    set_status browser tests, calendar handlers chain update_data() ->
    (later, inside render_list) get_data() within a single invocation
    (pick_calendar_day, paginate), so a real read-your-writes fake is
    needed to exercise that path faithfully.
    """

    def __init__(self, **initial):
        self.data = dict(initial)
        self.states = []
        self.cleared = 0

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)
        return dict(self.data)

    async def set_state(self, state):
        self.states.append(state)

    async def clear(self):
        self.data = {}
        self.states.append(None)
        self.cleared += 1


class FakeAppointmentRepository:
    def __init__(self, appointment=None):
        self.appointment = appointment
        self.status_updates = []
        self.count_calls = []
        self.page_calls = []

    async def get_appointment_by_id(self, appointment_id):
        return self.appointment

    async def get_appointments_by_doctor_and_date(self, doctor_id, date):
        return []

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.appointment.status = status
        self.status_updates.append((appointment_id, status))

    async def count_appointments_by_date_and_status(
        self, date_str, status, clinic_id, doctor_id=None, tab_bucket=False,
    ):
        self.count_calls.append((date_str, status, clinic_id, doctor_id, tab_bucket))
        if self.appointment and self.appointment.status == status:
            return 1
        return 0

    async def get_appointments_by_date_and_status_page(
        self, date_str, status, page, clinic_id, doctor_id=None, per_page=10, tab_bucket=False,
    ):
        self.page_calls.append((date_str, status, page, clinic_id, doctor_id, tab_bucket))
        if self.appointment and self.appointment.status == status:
            return [self.appointment]
        return []


class FakeUserRepo:
    def __init__(self, admins_by_telegram_id, staff_by_clinic=None):
        self.admins = admins_by_telegram_id
        self.staff_by_clinic = staff_by_clinic or {}

    async def get_user_by_telegram_id(self, telegram_user_id):
        return self.admins.get(telegram_user_id)

    async def get_staff_users_by_clinic_id(self, clinic_id):
        return self.staff_by_clinic.get(clinic_id, [])


class FakeStaffRepo:
    def __init__(self, staff_by_telegram_id, staff_by_clinic=None):
        self.staff = staff_by_telegram_id
        self.staff_by_clinic = staff_by_clinic or {}

    async def get_staff(self, telegram_user_id):
        return self.staff.get(telegram_user_id)

    async def get_staff_by_clinic_id(self, clinic_id):
        return self.staff_by_clinic.get(clinic_id, [])


class FakeClinicRepo:
    def __init__(self, clinics_by_id):
        self.clinics = clinics_by_id

    async def get_clinic_by_id(self, clinic_id):
        return self.clinics.get(clinic_id)


def _own_admin():
    return User(
        full_name="Petrov Petr",
        phone="+998907654321",
        role=Role.ADMIN,
        telegram_user_id=OWN_ADMIN_TELEGRAM_ID,
        ID=1,
        clinic_id=1,
        clinic_name="Zub Mudrosti",
    )


def _clinic_admin():
    return User(
        full_name="Ivanova Irina",
        phone="+998901112233",
        role=Role.ADMIN,
        telegram_user_id=CLINIC_ADMIN_TELEGRAM_ID,
        ID=3,
        clinic_id=1,
        clinic_name="Zub Mudrosti",
    )


def _build_router(appointment_repo, notification_service=None, appointment_scheduler=None):
    own_admin = _own_admin()
    clinic_admin = _clinic_admin()

    # Mirrors production reality (see staff_repository.py's is_doctor migration):
    # visibility_scope="clinic" admins have is_doctor=False, visibility_scope="own"
    # doctors have is_doctor=True. Clinic 1 therefore resolves to exactly 1 doctor
    # (OWN_ADMIN), keeping it below the >=2 threshold that would trigger the
    # calendar doctor-filter picker in these scoping-only tests.
    staff_records = {
        OWN_ADMIN_TELEGRAM_ID: Staff(
            telegram_user_id=OWN_ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="own", is_doctor=True,
        ),
        CLINIC_ADMIN_TELEGRAM_ID: Staff(
            telegram_user_id=CLINIC_ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="clinic", is_doctor=False,
        ),
    }
    user_repo = FakeUserRepo(
        {OWN_ADMIN_TELEGRAM_ID: own_admin, CLINIC_ADMIN_TELEGRAM_ID: clinic_admin},
        staff_by_clinic={1: [own_admin, clinic_admin]},
    )
    staff_repo = FakeStaffRepo(staff_records, staff_by_clinic={1: list(staff_records.values())})
    clinic_repo = FakeClinicRepo({1: Clinic(clinic_id=1, name="Zub Mudrosti", token="t")})
    return create_admin_appointment_browser_router(
        "zb", appointment_repo, user_repo, staff_repo, clinic_repo,
        appointment_scheduler=appointment_scheduler, notification_service=notification_service,
    )


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _find_message_handler_object(router, name):
    for handler in router.message.handlers:
        if handler.callback.__name__ == name:
            return handler
    raise AssertionError(f"message handler {name} not found")


def _callback_query(telegram_user_id=OWN_ADMIN_TELEGRAM_ID):
    callback_query = MagicMock()
    callback_query.from_user.id = telegram_user_id
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _appointment(**overrides):
    fields = dict(
        clinic_id=1,
        client_id=7,
        doctor_id=1,
        datetime="2026-07-17 10:00",
        purpose="Konsultatsiya",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.CONFIRMED,
        id=1,
    )
    fields.update(overrides)
    return Appointment(**fields)


# --- open_calendar ---

@pytest.mark.asyncio
async def test_open_calendar_clears_state_and_opens_grid_at_clamped_current_month():
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo)
    open_calendar = _find_handler(router, "open_calendar_callback")

    callback_query = _callback_query()
    callback_query.__class__ = CallbackQuery
    state = FakeState(stale_key="stale_value")

    await open_calendar(callback_query, state)

    today = get_current_tashkent_datetime().date()
    expected_year, expected_month = clamp_month_to_range(today.year, today.month)

    assert state.cleared == 1
    assert "stale_key" not in state.data
    assert state.data["calendar_year"] == expected_year
    assert state.data["calendar_month"] == expected_month
    assert state.states[-1] == AppointmentBrowserStates.calendar_month

    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert kwargs["reply_markup"] == appointment_calendar_kb(expected_year, expected_month)


# --- open_calendar_message (text-triggered entrypoint: button + /calendar slash command) ---

@pytest.mark.asyncio
async def test_open_calendar_message_filter_accepts_slash_command_and_button_text():
    """Routing-level guard: the F.text.in_({"/calendar", "📆 Календарь"}) filter
    on open_calendar_message must accept both triggers and reject unrelated text."""
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo)
    handler = _find_message_handler_object(router, "open_calendar_message")

    for text in ("/calendar", "📆 Календарь"):
        message = MagicMock()
        message.text = text
        matched, _ = await handler.check(message)
        assert matched is True, text

    message = MagicMock()
    message.text = "some other text"
    matched, _ = await handler.check(message)
    assert matched is False


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger_text", ["/calendar", "📆 Календарь"])
async def test_open_calendar_message_opens_grid_at_clamped_current_month(trigger_text):
    """/calendar must trigger the exact same open_calendar_message handler
    (and therefore the exact same show_calendar behaviour) as the pre-existing
    "📆 Календарь" reply-keyboard button text."""
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo)
    open_calendar_message = _find_message_handler_object(router, "open_calendar_message").callback

    sent_message = MagicMock()
    sent_message.chat.id = 100
    sent_message.message_id = 555

    message = MagicMock()
    message.text = trigger_text
    message.from_user.id = OWN_ADMIN_TELEGRAM_ID
    message.answer = AsyncMock(return_value=sent_message)
    state = FakeState(stale_key="stale_value")

    await open_calendar_message(message, state)

    today = get_current_tashkent_datetime().date()
    expected_year, expected_month = clamp_month_to_range(today.year, today.month)

    assert "stale_key" not in state.data
    assert state.data["calendar_year"] == expected_year
    assert state.data["calendar_month"] == expected_month
    assert state.data["card_chat_id"] == 100
    assert state.data["card_message_id"] == 555
    assert state.states[-1] == AppointmentBrowserStates.calendar_month

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.await_args
    assert kwargs["reply_markup"] == appointment_calendar_kb(expected_year, expected_month)


# --- change_calendar_month ---

@pytest.mark.asyncio
async def test_change_calendar_month_updates_fsm_and_rerenders_grid():
    """Handler-level check that a pre-computed wrapped (year, month) pair -
    e.g. what appointment_calendar_kb would embed for a '>' press from
    Dec 2027 - propagates into FSM state and the re-rendered grid. The wrap
    math itself (shift_month/clamp_month_to_range) is already covered at the
    pure-function and keyboard level in test_appointment_calendar_kb.py."""
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo)
    change_calendar_month = _find_handler(router, "change_calendar_month")

    callback_query = _callback_query()
    state = FakeState()
    callback_data = ApptCalendarMonthCB(year=2026, month=1)

    await change_calendar_month(callback_query, callback_data, state)

    assert state.data["calendar_year"] == 2026
    assert state.data["calendar_month"] == 1
    assert state.states[-1] == AppointmentBrowserStates.calendar_month

    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert kwargs["reply_markup"] == appointment_calendar_kb(2026, 1)


@pytest.mark.asyncio
async def test_change_calendar_month_clamps_forged_month_above_twelve():
    """A forged/malformed ApptCalendarMonthCB (e.g. month=13, which can never
    be produced by the keyboard's own shift_month/nav buttons) used to crash
    the handler - format_month_label's _MONTH_NAMES_RU[13] raises KeyError,
    and get_month_grid's datetime(year, 13, 1) raises ValueError. The handler
    now runs the callback's (year, month) through clamp_month_to_range first,
    so it must survive and settle on the nearest valid month instead."""
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo)
    change_calendar_month = _find_handler(router, "change_calendar_month")

    callback_query = _callback_query()
    state = FakeState()
    callback_data = ApptCalendarMonthCB(year=2026, month=13)

    await change_calendar_month(callback_query, callback_data, state)

    assert state.data["calendar_year"] == 2026
    assert state.data["calendar_month"] == 12
    assert state.states[-1] == AppointmentBrowserStates.calendar_month

    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert kwargs["reply_markup"] == appointment_calendar_kb(2026, 12)


@pytest.mark.asyncio
async def test_change_calendar_month_clamps_forged_month_below_one():
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo)
    change_calendar_month = _find_handler(router, "change_calendar_month")

    callback_query = _callback_query()
    state = FakeState()
    callback_data = ApptCalendarMonthCB(year=2026, month=0)

    await change_calendar_month(callback_query, callback_data, state)

    assert state.data["calendar_year"] == 2026
    assert state.data["calendar_month"] == 1
    assert state.states[-1] == AppointmentBrowserStates.calendar_month

    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert kwargs["reply_markup"] == appointment_calendar_kb(2026, 1)


@pytest.mark.asyncio
async def test_change_calendar_month_clamps_forged_year_outside_range():
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo)
    change_calendar_month = _find_handler(router, "change_calendar_month")

    callback_query = _callback_query()
    state = FakeState()
    callback_data = ApptCalendarMonthCB(year=2030, month=13)

    await change_calendar_month(callback_query, callback_data, state)

    assert state.data["calendar_year"] == CALENDAR_MAX_YEAR
    assert state.data["calendar_month"] == 12
    assert state.states[-1] == AppointmentBrowserStates.calendar_month

    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert kwargs["reply_markup"] == appointment_calendar_kb(CALENDAR_MAX_YEAR, 12)


# --- pick_calendar_day ---

@pytest.mark.asyncio
async def test_pick_calendar_day_sets_calendar_day_state_and_renders_tab_menu():
    appointment = _appointment()
    appt_repo = FakeAppointmentRepository(appointment)
    router = _build_router(appt_repo)
    pick_calendar_day = _find_handler(router, "pick_calendar_day")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    state = FakeState()
    callback_data = ApptCalendarDayCB(year=2026, month=7, day=17)

    await pick_calendar_day(callback_query, callback_data, state)

    assert state.data["calendar_date"] == "2026-07-17"
    assert state.data["calendar_year"] == 2026
    assert state.data["calendar_month"] == 7
    assert state.states[0] == AppointmentBrowserStates.calendar_day

    # own-scope admin -> query is scoped to clinic_id=1, doctor_id=1 (their own ID)
    assert appt_repo.count_calls == [("2026-07-17", AppointmentStatus.CONFIRMED, 1, 1, True)]
    assert appt_repo.page_calls == [("2026-07-17", AppointmentStatus.CONFIRMED, 1, 1, 1, True)]

    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args

    back_target = ApptCalendarMonthCB(year=2026, month=7).pack()
    expected_markup = appointment_list_kb(
        [appointment], "calendar", 1, 1, "confirmed",
        back_callback_data=back_target, back_label="⬅️ К календарю",
    )
    assert kwargs["reply_markup"] == expected_markup


@pytest.mark.asyncio
async def test_pick_calendar_day_scopes_to_clinic_only_for_clinic_scope_admin():
    appointment = _appointment(doctor_id=55)
    appt_repo = FakeAppointmentRepository(appointment)
    router = _build_router(appt_repo)
    pick_calendar_day = _find_handler(router, "pick_calendar_day")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    state = FakeState()
    callback_data = ApptCalendarDayCB(year=2026, month=7, day=17)

    await pick_calendar_day(callback_query, callback_data, state)

    # clinic-scope admin -> doctor_id is not restricted (None)
    assert appt_repo.count_calls == [("2026-07-17", AppointmentStatus.CONFIRMED, 1, None, True)]
    assert appt_repo.page_calls == [("2026-07-17", AppointmentStatus.CONFIRMED, 1, 1, None, True)]


@pytest.mark.asyncio
async def test_pick_calendar_day_back_button_targets_the_days_own_month_not_stale_fsm_month():
    """3-level back-nav: the day-list's 'Back' button must return to the SAME
    month/year that was active when the day was picked - which is always the
    (year, month) embedded in ApptCalendarDayCB itself, not whatever stale
    calendar_year/calendar_month happened to be left in FSM state from a
    previous month-grid visit."""
    appointment = _appointment()
    appt_repo = FakeAppointmentRepository(appointment)
    router = _build_router(appt_repo)
    pick_calendar_day = _find_handler(router, "pick_calendar_day")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    # Stale FSM data from an earlier month-grid visit to a different month.
    state = FakeState(calendar_year=2026, calendar_month=3)
    callback_data = ApptCalendarDayCB(year=2026, month=8, day=5)

    await pick_calendar_day(callback_query, callback_data, state)

    assert state.data["calendar_year"] == 2026
    assert state.data["calendar_month"] == 8

    args, kwargs = callback_query.message.edit_text.await_args
    back_target = ApptCalendarMonthCB(year=2026, month=8).pack()
    assert back_target in str(kwargs["reply_markup"])


@pytest.mark.asyncio
async def test_pick_calendar_day_clamps_forged_day_above_month_length():
    """A forged/malformed ApptCalendarDayCB (e.g. day=31 for February, which
    can never be produced by the keyboard's own generate_month_days) used to
    produce an invalid ISO date string like '2026-02-31'. The handler now
    runs the callback's (year, month, day) through clamp_calendar_date first,
    so it must survive and settle on February's actual last day instead."""
    appointment = _appointment()
    appt_repo = FakeAppointmentRepository(appointment)
    router = _build_router(appt_repo)
    pick_calendar_day = _find_handler(router, "pick_calendar_day")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    state = FakeState()
    callback_data = ApptCalendarDayCB(year=2026, month=2, day=31)

    await pick_calendar_day(callback_query, callback_data, state)

    assert state.data["calendar_date"] == "2026-02-28"
    assert state.data["calendar_year"] == 2026
    assert state.data["calendar_month"] == 2
    assert state.states[0] == AppointmentBrowserStates.calendar_day

    callback_query.message.edit_text.assert_awaited_once()


# --- paginate (tab switch / page nav while inside calendar mode) ---

@pytest.mark.asyncio
async def test_paginate_handler_calendar_mode_reads_calendar_date_from_fsm():
    """Simulates switching tabs while browsing a calendar day's results
    (clicking a tab button re-enters via ApptPageCB(mode='calendar', ...)),
    exercising the same render_list(mode='calendar') branch, but through the
    generic paginate() entrypoint rather than pick_calendar_day."""
    appointment = _appointment(status=AppointmentStatus.PENDING)
    appt_repo = FakeAppointmentRepository(appointment)
    router = _build_router(appt_repo)
    paginate = _find_handler(router, "paginate")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    state = FakeState(calendar_date="2026-07-17", calendar_year=2026, calendar_month=7)
    callback_data = ApptPageCB(mode="calendar", page=1, tab="pending")

    await paginate(callback_query, callback_data, state)

    assert appt_repo.count_calls == [("2026-07-17", AppointmentStatus.PENDING, 1, 1, True)]
    assert appt_repo.page_calls == [("2026-07-17", AppointmentStatus.PENDING, 1, 1, 1, True)]

    args, kwargs = callback_query.message.edit_text.await_args
    back_target = ApptCalendarMonthCB(year=2026, month=7).pack()
    assert back_target in str(kwargs["reply_markup"])


# --- card actions carry mode="calendar" through correctly ---

@pytest.mark.asyncio
async def test_open_card_with_calendar_mode_targets_calendar_list_on_back():
    appointment = _appointment()
    appt_repo = FakeAppointmentRepository(appointment)
    router = _build_router(appt_repo)
    open_card = _find_handler(router, "open_card")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    state = FakeState(calendar_date="2026-07-17", calendar_year=2026, calendar_month=7)
    callback_data = ApptCardCB(appointment_id=1, mode="calendar", page=1, tab="confirmed")

    await open_card(callback_query, callback_data, state)

    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args

    # The card's "back to list" button must round-trip through mode="calendar"
    # (ApptPageCB(mode="calendar", ...)), not silently fall back to mode="list".
    back_to_list_target = ApptPageCB(mode="calendar", page=1, tab="confirmed").pack()
    assert back_to_list_target in str(kwargs["reply_markup"])


@pytest.mark.asyncio
async def test_set_status_with_calendar_mode_rerenders_card_targeting_calendar_list():
    appointment = _appointment(status=AppointmentStatus.PENDING)
    appt_repo = FakeAppointmentRepository(appointment)
    router = _build_router(appt_repo)
    set_status = _find_handler(router, "set_status")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    state = FakeState(calendar_date="2026-07-17", calendar_year=2026, calendar_month=7)
    callback_data = ApptActionCB(
        action="set_status", appointment_id=1, mode="calendar", page=1, value="confirmed",
    )

    await set_status(callback_query, callback_data, state)

    assert appt_repo.status_updates == [(1, AppointmentStatus.CONFIRMED)]

    args, kwargs = callback_query.message.edit_text.await_args
    # mode="calendar" survives the in-place card re-render (regression guard:
    # this must not silently degrade to mode="list").
    #
    # KNOWN PRE-EXISTING LIMITATION (not introduced by the calendar feature,
    # not to be fixed here): ApptActionCB carries no `tab`, so set_status's
    # in-place re-render always targets tab="" here, which paginate()/
    # render_list then defaults to "confirmed" - returning to the list after
    # a status change lands on the confirmed tab regardless of which tab
    # (e.g. "pending") the admin actually came from. This assertion pins
    # today's (buggy but expected) behavior so a future fix is a deliberate,
    # visible test change rather than a silent regression.
    # Exact equality (not `in`/substring): tab="" packs to "appt_page:calendar:1:",
    # which is a *prefix* of "appt_page:calendar:1:pending" etc, so a substring
    # check here would keep passing even if the limitation got fixed and the
    # real tab started being carried through. Extract the actual back button
    # (last row, single button - see appointment_card_kb) to pin the exact value.
    back_button = kwargs["reply_markup"].inline_keyboard[-1][0]
    assert back_button.callback_data == ApptPageCB(mode="calendar", page=1, tab="").pack()
