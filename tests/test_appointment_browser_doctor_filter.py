"""Doctor-filter picker tests for appointment_browser.py.

For clinic-admin users (visibility_scope="clinic"), a "pick a doctor" filter
step now appears before the appointment status-tab list, for search-by-name,
search-by-phone, and full-pagination ("list") entry points. Doctors (own/None
scope) never see this step, and the calendar mode must never pick up a
doctor filter chosen earlier in list/search/phone mode (see
maybe_prompt_doctor_filter / resolve_filtered_doctor_id / apply_doctor_filter
in bot/handlers/admin/appointment_management/appointment_browser.py).

maybe_prompt_doctor_filter and resolve_filtered_doctor_id are private
closures inside create_admin_appointment_browser_router (not registered
router handlers), so they are exercised here indirectly through the public
handlers that call them (search_all, approve_search, paginate, finish_delete)
rather than invoked directly. apply_doctor_filter IS a registered handler
and is reached via _find_handler like the rest of this test suite.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.admin.appointment_management.appointment_browser import (
    create_admin_appointment_browser_router,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import (
    ApptCalendarDayCB,
    ApptCalendarMonthCB,
    ApptDoctorFilterCB,
    ApptPageCB,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_kb import (
    appointment_doctor_filter_kb,
)
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.states.admin.record_management.appointment_browser_states import AppointmentBrowserStates
from bot.utils.role import Role


OWN_ADMIN_TELEGRAM_ID = 999
OWN_ADMIN_ID = 1
CLINIC_ADMIN_TELEGRAM_ID = 2000
CLINIC_ADMIN_ID = 3
DOCTOR_COLLEAGUE_TELEGRAM_ID = 2001
DOCTOR_COLLEAGUE_ID = 4


class FakeState:
    """Dict-backed stand-in for FSMContext (mirrors test_appointment_calendar_
    handlers.py FakeState). Needed here because apply_doctor_filter and
    paginate both write state and then read it back (update_data ->
    get_data) within a single invocation -- a static MagicMock with a frozen
    get_data() return value would silently break that readback."""

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
    """Supports every pagination/delete method render_list and finish_delete
    can reach, so tests drive the real handlers end to end instead of
    stubbing out AppointmentManagement/AppointmentPaginationService. Records
    the doctor_id each pagination call was made with, which is what the
    doctor-filter tests actually assert on."""

    def __init__(self, appointments=None):
        self.appointments = list(appointments or [])
        self.deleted = []
        self.status_page_calls = []
        self.name_page_calls = []
        self.date_page_calls = []
        self.client_id_calls = []

    async def get_appointment_by_id(self, appointment_id):
        return next((a for a in self.appointments if a.id == appointment_id), None)

    async def appointment_exists(self, appointment_id):
        return any(a.id == appointment_id for a in self.appointments)

    async def delete_appointment(self, appointment_id):
        self.deleted.append(appointment_id)
        self.appointments = [a for a in self.appointments if a.id != appointment_id]

    async def count_appointments_by_status(self, status, clinic_id, doctor_id=None, tab_bucket=False):
        return 0

    async def get_appointments_by_status_page(self, status, page, clinic_id, doctor_id, per_page, tab_bucket=False):
        self.status_page_calls.append((status, page, clinic_id, doctor_id, per_page, tab_bucket))
        return []

    async def count_appointments_by_name_and_status(
        self, full_name, status, clinic_id, doctor_id=None, tab_bucket=False,
    ):
        return 0

    async def get_appointments_by_name_and_status_page(
        self, full_name, status, page, clinic_id, doctor_id=None, per_page=10, tab_bucket=False,
    ):
        self.name_page_calls.append((full_name, status, page, clinic_id, doctor_id, per_page, tab_bucket))
        return []

    async def get_appointments_by_client_id(self, client_id, clinic_id, doctor_id=None):
        self.client_id_calls.append((client_id, clinic_id, doctor_id))
        return []

    async def count_appointments_by_date_and_status(
        self, date_str, status, clinic_id, doctor_id=None, tab_bucket=False,
    ):
        return 0

    async def get_appointments_by_date_and_status_page(
        self, date_str, status, page, clinic_id, doctor_id=None, per_page=10, tab_bucket=False,
    ):
        self.date_page_calls.append((date_str, status, page, clinic_id, doctor_id, per_page, tab_bucket))
        return []


class FakeUserRepo:
    def __init__(self, users_by_telegram_id, staff_by_clinic=None):
        self.users = users_by_telegram_id
        self.staff_by_clinic = staff_by_clinic or {}

    async def get_user_by_telegram_id(self, telegram_user_id):
        return self.users.get(telegram_user_id)

    async def get_staff_users_by_clinic_id(self, clinic_id):
        return self.staff_by_clinic.get(clinic_id, [])

    async def get_client_by_phone_in_clinic(self, phone, clinic_id):
        return None


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
        full_name="Petrov Petr", phone="+998907654321", role=Role.ADMIN,
        telegram_user_id=OWN_ADMIN_TELEGRAM_ID, ID=OWN_ADMIN_ID, clinic_id=1, clinic_name="Zub Mudrosti",
    )


def _clinic_admin():
    return User(
        full_name="Ivanova Irina", phone="+998901112233", role=Role.ADMIN,
        telegram_user_id=CLINIC_ADMIN_TELEGRAM_ID, ID=CLINIC_ADMIN_ID, clinic_id=1, clinic_name="Zub Mudrosti",
    )


def _doctor_colleague():
    return User(
        full_name="Sidorov Sidor", phone="+998901234567", role=Role.ADMIN,
        telegram_user_id=DOCTOR_COLLEAGUE_TELEGRAM_ID, ID=DOCTOR_COLLEAGUE_ID, clinic_id=1, clinic_name="Zub Mudrosti",
    )


def _build_router(appointment_repo, *, clinic_has_two_doctors=False):
    """clinic_has_two_doctors=False leaves the clinic-admin as the only
    doctor in the clinic (1 total) -- the filter still must not offer a
    no-op picker. =True adds a second own-scope doctor so the >= 2
    threshold is crossed."""
    clinic_admin = _clinic_admin()
    own_admin = _own_admin()

    users_by_telegram_id = {
        OWN_ADMIN_TELEGRAM_ID: own_admin,
        CLINIC_ADMIN_TELEGRAM_ID: clinic_admin,
    }
    staff_in_clinic = [clinic_admin]
    staff_records = {
        OWN_ADMIN_TELEGRAM_ID: Staff(
            telegram_user_id=OWN_ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="own", is_doctor=True,
        ),
        CLINIC_ADMIN_TELEGRAM_ID: Staff(
            telegram_user_id=CLINIC_ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="clinic", is_doctor=True,
        ),
    }

    if clinic_has_two_doctors:
        doctor_colleague = _doctor_colleague()
        users_by_telegram_id[DOCTOR_COLLEAGUE_TELEGRAM_ID] = doctor_colleague
        staff_in_clinic = [clinic_admin, doctor_colleague]
        staff_records[DOCTOR_COLLEAGUE_TELEGRAM_ID] = Staff(
            telegram_user_id=DOCTOR_COLLEAGUE_TELEGRAM_ID, clinic_id=1, visibility_scope="own", is_doctor=True,
        )

    user_repo = FakeUserRepo(users_by_telegram_id, staff_by_clinic={1: staff_in_clinic})
    staff_repo = FakeStaffRepo(staff_records, staff_by_clinic={1: list(staff_records.values())})
    clinic_repo = FakeClinicRepo({1: Clinic(clinic_id=1, name="Zub Mudrosti", token="t")})

    return create_admin_appointment_browser_router(appointment_repo, user_repo, staff_repo, clinic_repo)


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _callback_query(telegram_user_id):
    callback_query = MagicMock()
    callback_query.from_user.id = telegram_user_id
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


# --- maybe_prompt_doctor_filter (via search_all) ---

@pytest.mark.asyncio
async def test_search_all_skips_picker_for_doctor_caller():
    """An own-scope doctor always resolves a concrete doctor_id via
    resolve_admin_appointment_filter, so list_clinic_doctors_for_filter
    short-circuits to [] -- search_all must go straight to render_list,
    exactly as before this feature existed."""
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=True)
    search_all = _find_handler(router, "search_all")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    state = FakeState()

    await search_all(callback_query, state)

    assert AppointmentBrowserStates.pick_doctor_filter not in state.states
    assert "pending_render" not in state.data
    callback_query.message.edit_text.assert_awaited_once()
    args, _ = callback_query.message.edit_text.await_args
    assert "Выберите врача" not in args[0]


@pytest.mark.asyncio
async def test_search_all_skips_picker_when_clinic_has_fewer_than_two_doctors():
    """A clinic-scope admin whose clinic currently has only 1 doctor (this
    admin) must not be shown a one-option, no-op picker."""
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=False)
    search_all = _find_handler(router, "search_all")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    state = FakeState()

    await search_all(callback_query, state)

    assert AppointmentBrowserStates.pick_doctor_filter not in state.states
    assert "pending_render" not in state.data
    callback_query.message.edit_text.assert_awaited_once()
    args, _ = callback_query.message.edit_text.await_args
    assert "Выберите врача" not in args[0]


@pytest.mark.asyncio
async def test_search_all_shows_picker_for_clinic_admin_with_two_or_more_doctors():
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=True)
    search_all = _find_handler(router, "search_all")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    state = FakeState()

    await search_all(callback_query, state)

    assert state.states[-1] == AppointmentBrowserStates.pick_doctor_filter
    assert state.data["pending_render"] == {"mode": "list", "page": 1, "tab": "confirmed"}
    callback_query.message.edit_text.assert_awaited_once()
    args, _ = callback_query.message.edit_text.await_args
    assert args[0] == "Выберите врача для фильтрации:"
    # Picker takes over the screen -- render_list must never have run.
    assert appt_repo.status_page_calls == []


# --- resolve_filtered_doctor_id (via paginate) ---

@pytest.mark.asyncio
async def test_paginate_applies_doctor_filter_override_in_list_mode():
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=True)
    paginate = _find_handler(router, "paginate")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    state = FakeState(doctor_filter_id=DOCTOR_COLLEAGUE_ID)
    callback_data = ApptPageCB(mode="list", page=2, tab="confirmed")

    await paginate(callback_query, callback_data, state)

    assert appt_repo.status_page_calls
    _, _, _, doctor_id, _, _ = appt_repo.status_page_calls[-1]
    assert doctor_id == DOCTOR_COLLEAGUE_ID


@pytest.mark.asyncio
async def test_paginate_calendar_mode_never_leaks_doctor_filter():
    """The highest-risk invariant of this feature: a doctor filter picked
    earlier in list/search/phone mode must NEVER apply to calendar mode,
    which keeps resolving straight through resolve_admin_appointment_filter.
    doctor_filter_id is deliberately set to a value distinct from what
    resolve_admin_appointment_filter itself would return (None, since this
    caller is clinic-scoped) so this assertion can actually fail if the
    FILTERABLE_MODES guard is ever removed or widened to include calendar."""
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=True)
    paginate = _find_handler(router, "paginate")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    state = FakeState(
        doctor_filter_id=DOCTOR_COLLEAGUE_ID,
        calendar_date="2026-08-01", calendar_year=2026, calendar_month=8,
    )
    callback_data = ApptPageCB(mode="calendar", page=1, tab="confirmed")

    await paginate(callback_query, callback_data, state)

    assert appt_repo.date_page_calls
    _, _, _, _, doctor_id, _, _ = appt_repo.date_page_calls[-1]
    assert doctor_id is None


# --- apply_doctor_filter ---

@pytest.mark.asyncio
async def test_apply_doctor_filter_stores_specific_doctor_and_renders_filtered_list():
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=True)
    apply_doctor_filter = _find_handler(router, "apply_doctor_filter")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    state = FakeState(pending_render={"mode": "list", "page": 1, "tab": "confirmed"})
    callback_data = ApptDoctorFilterCB(doctor_id=DOCTOR_COLLEAGUE_ID)

    await apply_doctor_filter(callback_query, callback_data, state)

    assert state.data["doctor_filter_id"] == DOCTOR_COLLEAGUE_ID
    assert state.states[-1] is None
    assert appt_repo.status_page_calls
    _, _, _, doctor_id, _, _ = appt_repo.status_page_calls[-1]
    assert doctor_id == DOCTOR_COLLEAGUE_ID


@pytest.mark.asyncio
async def test_apply_doctor_filter_all_sentinel_clears_filter():
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=True)
    apply_doctor_filter = _find_handler(router, "apply_doctor_filter")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    state = FakeState(pending_render={"mode": "list", "page": 1, "tab": "confirmed"})
    callback_data = ApptDoctorFilterCB(doctor_id=0)

    await apply_doctor_filter(callback_query, callback_data, state)

    assert "doctor_filter_id" in state.data
    assert state.data["doctor_filter_id"] is None
    assert appt_repo.status_page_calls
    _, _, _, doctor_id, _, _ = appt_repo.status_page_calls[-1]
    assert doctor_id is None


@pytest.mark.asyncio
async def test_apply_doctor_filter_restores_confirm_search_state_for_search_mode():
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=True)
    apply_doctor_filter = _find_handler(router, "apply_doctor_filter")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    state = FakeState(
        pending_render={"mode": "search", "page": 1, "tab": "confirmed"},
        search_data={"full_name": "Ivanov Ivan"},
    )
    callback_data = ApptDoctorFilterCB(doctor_id=DOCTOR_COLLEAGUE_ID)

    await apply_doctor_filter(callback_query, callback_data, state)

    assert state.states[-1] == AppointmentBrowserStates.confirm_search
    assert state.data["doctor_filter_id"] == DOCTOR_COLLEAGUE_ID
    assert appt_repo.name_page_calls
    _, _, _, _, doctor_id, _, _ = appt_repo.name_page_calls[-1]
    assert doctor_id == DOCTOR_COLLEAGUE_ID


# --- pick_calendar_day (calendar mode's own doctor-filter step) ---

@pytest.mark.asyncio
async def test_pick_calendar_day_shows_picker_for_clinic_admin_with_two_or_more_doctors():
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=True)
    pick_calendar_day = _find_handler(router, "pick_calendar_day")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    state = FakeState()
    callback_data = ApptCalendarDayCB(year=2026, month=7, day=17)

    await pick_calendar_day(callback_query, callback_data, state)

    assert state.states[-1] == AppointmentBrowserStates.pick_doctor_filter
    assert state.data["pending_render"] == {"mode": "calendar", "page": 1, "tab": "confirmed"}
    # Picker takes over the screen -- render_list must never have run.
    assert appt_repo.date_page_calls == []

    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == "Выберите врача для фильтрации:"

    back_target = ApptCalendarMonthCB(year=2026, month=7).pack()
    expected_markup = appointment_doctor_filter_kb(
        [_clinic_admin(), _doctor_colleague()], back_callback_data=back_target, back_label="⬅️ К календарю",
    )
    assert kwargs["reply_markup"] == expected_markup


@pytest.mark.asyncio
async def test_pick_calendar_day_skips_picker_for_doctor_caller():
    """An own-scope doctor always resolves a concrete doctor_id via
    resolve_admin_appointment_filter, so list_clinic_doctors_for_filter
    short-circuits to [] -- pick_calendar_day must render the day list
    directly, exactly as before this feature existed."""
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=True)
    pick_calendar_day = _find_handler(router, "pick_calendar_day")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    state = FakeState()
    callback_data = ApptCalendarDayCB(year=2026, month=7, day=17)

    await pick_calendar_day(callback_query, callback_data, state)

    assert AppointmentBrowserStates.pick_doctor_filter not in state.states
    assert "pending_render" not in state.data
    assert appt_repo.date_page_calls
    _, _, _, _, doctor_id, _, _ = appt_repo.date_page_calls[-1]
    assert doctor_id == OWN_ADMIN_ID


@pytest.mark.asyncio
async def test_pick_calendar_day_skips_picker_when_clinic_has_fewer_than_two_doctors():
    """A clinic-scope admin whose clinic currently has only 1 doctor must not
    be shown a one-option, no-op picker."""
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=False)
    pick_calendar_day = _find_handler(router, "pick_calendar_day")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    state = FakeState()
    callback_data = ApptCalendarDayCB(year=2026, month=7, day=17)

    await pick_calendar_day(callback_query, callback_data, state)

    assert AppointmentBrowserStates.pick_doctor_filter not in state.states
    assert "pending_render" not in state.data
    assert appt_repo.date_page_calls
    _, _, _, _, doctor_id, _, _ = appt_repo.date_page_calls[-1]
    assert doctor_id is None


@pytest.mark.asyncio
async def test_pick_calendar_day_honors_existing_specific_doctor_filter_in_state():
    """A calendar_doctor_filter_id already present in state (chosen on a
    previous day pick within the same calendar session) must be honored
    directly, without re-prompting."""
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=True)
    pick_calendar_day = _find_handler(router, "pick_calendar_day")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    state = FakeState(calendar_doctor_filter_id=DOCTOR_COLLEAGUE_ID)
    callback_data = ApptCalendarDayCB(year=2026, month=7, day=17)

    await pick_calendar_day(callback_query, callback_data, state)

    assert AppointmentBrowserStates.pick_doctor_filter not in state.states
    assert "pending_render" not in state.data
    assert appt_repo.date_page_calls
    _, _, _, _, doctor_id, _, _ = appt_repo.date_page_calls[-1]
    assert doctor_id == DOCTOR_COLLEAGUE_ID


@pytest.mark.asyncio
async def test_pick_calendar_day_honors_existing_all_doctors_sentinel_in_state():
    """calendar_doctor_filter_id=None (the 'all doctors' sentinel written by
    apply_doctor_filter for the '👥 Все врачи' choice) must override even an
    own-scope doctor's normally-restricted own doctor_id, and must not
    re-trigger the picker."""
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=True)
    pick_calendar_day = _find_handler(router, "pick_calendar_day")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    state = FakeState(calendar_doctor_filter_id=None)
    callback_data = ApptCalendarDayCB(year=2026, month=7, day=17)

    await pick_calendar_day(callback_query, callback_data, state)

    assert AppointmentBrowserStates.pick_doctor_filter not in state.states
    assert appt_repo.date_page_calls
    _, _, _, _, doctor_id, _, _ = appt_repo.date_page_calls[-1]
    assert doctor_id is None


# --- apply_doctor_filter (calendar mode) ---

@pytest.mark.asyncio
async def test_apply_doctor_filter_stores_calendar_filter_and_restores_calendar_day_state():
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=True)
    apply_doctor_filter = _find_handler(router, "apply_doctor_filter")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    state = FakeState(
        pending_render={"mode": "calendar", "page": 1, "tab": "confirmed"},
        calendar_date="2026-07-17", calendar_year=2026, calendar_month=7,
    )
    callback_data = ApptDoctorFilterCB(doctor_id=DOCTOR_COLLEAGUE_ID)

    await apply_doctor_filter(callback_query, callback_data, state)

    assert state.data["calendar_doctor_filter_id"] == DOCTOR_COLLEAGUE_ID
    assert "doctor_filter_id" not in state.data
    assert state.states[-1] == AppointmentBrowserStates.calendar_day
    assert appt_repo.date_page_calls
    _, _, _, _, doctor_id, _, _ = appt_repo.date_page_calls[-1]
    assert doctor_id == DOCTOR_COLLEAGUE_ID


@pytest.mark.asyncio
async def test_apply_doctor_filter_calendar_all_sentinel_clears_filter_and_restores_calendar_day_state():
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=True)
    apply_doctor_filter = _find_handler(router, "apply_doctor_filter")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    state = FakeState(
        pending_render={"mode": "calendar", "page": 1, "tab": "confirmed"},
        calendar_date="2026-07-17", calendar_year=2026, calendar_month=7,
    )
    callback_data = ApptDoctorFilterCB(doctor_id=0)

    await apply_doctor_filter(callback_query, callback_data, state)

    assert "calendar_doctor_filter_id" in state.data
    assert state.data["calendar_doctor_filter_id"] is None
    assert state.states[-1] == AppointmentBrowserStates.calendar_day
    assert appt_repo.date_page_calls
    _, _, _, _, doctor_id, _, _ = appt_repo.date_page_calls[-1]
    assert doctor_id is None


# --- calendar_doctor_filter_id isolation is bidirectional ---

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode, search_data",
    [
        ("list", None),
        ("search", {"full_name": "Ivanov Ivan"}),
        ("phone", {"client_id": 42}),
    ],
)
async def test_calendar_doctor_filter_never_leaks_into_list_search_phone_pagination(mode, search_data):
    """Mirror of test_paginate_calendar_mode_never_leaks_doctor_filter, in
    the opposite direction: a calendar_doctor_filter_id picked while browsing
    the calendar must never apply to list/search/phone mode, which only ever
    read doctor_filter_id (resolve_filtered_doctor_id keys off
    DOCTOR_FILTER_STATE_KEYS[mode], not the calendar-specific key)."""
    appt_repo = FakeAppointmentRepository()
    router = _build_router(appt_repo, clinic_has_two_doctors=True)
    paginate = _find_handler(router, "paginate")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    state_kwargs = {"calendar_doctor_filter_id": DOCTOR_COLLEAGUE_ID}
    if search_data is not None:
        state_kwargs["search_data"] = search_data
    state = FakeState(**state_kwargs)
    callback_data = ApptPageCB(mode=mode, page=1, tab="confirmed")

    await paginate(callback_query, callback_data, state)

    if mode == "list":
        assert appt_repo.status_page_calls
        _, _, _, doctor_id, _, _ = appt_repo.status_page_calls[-1]
    elif mode == "search":
        assert appt_repo.name_page_calls
        _, _, _, _, doctor_id, _, _ = appt_repo.name_page_calls[-1]
    else:
        assert appt_repo.client_id_calls
        _, _, doctor_id = appt_repo.client_id_calls[-1]

    assert doctor_id is None
