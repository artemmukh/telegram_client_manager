"""Handler-level tests for the calendar/slot-grid admin appointment creation
flow (bot/handlers/admin/appointment_management/appointment_creation.py).

Both zb and mm now run through the same month-grid calendar + slot-occupancy
grid (bot/config/clinic_instances.py::DATEPARSER_BY_INSTANCE == "slots" for
both instances). Covers: change_calendar_month, pick_calendar_day,
back_to_day_selection, view_occupied_slot, back_to_slot_grid, pick_slot --
plus begin_appointment_creation's calendar entry and the _ensure_staff_user_id
admin-as-default-doctor fallback it uses
(bot/handlers/utils/admin_utils/appointment_helpers.py).

Follows the direct-handler-call/fake-repository convention established in
test_appointment_creation_doctor_picker.py / test_appointment_creation_restart.py.
Where "now" matters (slot time-filtering), get_current_tashkent_datetime is
patched at its call sites -- the same approach already used for
MIN_LEAD_TIME tests in test_appointment_management.py -- rather than
asserting brittle real-clock-dependent output.
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config.booking_config import BOOKING_SLOTS
from bot.handlers.admin.appointment_management.appointment_creation import (
    create_admin_appointment_creation_router,
)
from bot.handlers.utils.admin_utils import appointment_helpers as ah
from bot.handlers.utils.admin_utils.appointment_calendar_helpers import format_month_label
from bot.handlers.utils.admin_utils.appointment_helpers import build_appointment_card
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import ApptCalendarDayCB, ApptCalendarMonthCB
from bot.keyboards.admin.record_management_kb.appointment_creation_cb import AdminOccupiedSlotCB
from bot.keyboards.admin.record_management_kb.appointment_kb import back_to_records_kb
from bot.keyboards.admin.record_management_kb.appointment_slot_kb import appointment_slot_grid_kb, occupied_slot_card_kb
from bot.keyboards.client.booking_cb import ClientBookSlotCB
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.services.utils.date_parser import format_datetime_for_display
from bot.states.admin.record_management.appointment_states import AppointmentCreationStates
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role

ADMIN_TELEGRAM_ID = 999
FIXED_NOW = datetime(2026, 7, 6, 9, 0)  # a Monday, matching test_booking_day_helpers.py


class FakeAppointmentRepository:
    def __init__(self, appointments=None):
        self.appointments = list(appointments or [])

    async def create_appointment(self, appointment):
        return appointment

    async def get_appointment_by_id(self, appointment_id):
        return next((a for a in self.appointments if a.id == appointment_id), None)

    async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None):
        if statuses is None:
            return [
                a for a in self.appointments
                if a.doctor_id == doctor_id and a.datetime.startswith(date)
                and a.status == AppointmentStatus.CONFIRMED
            ]

        return [
            a for a in self.appointments
            if a.doctor_id == doctor_id and a.datetime.startswith(date)
            and a.status in statuses
        ]


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


def _admin(staff_id=42, telegram_user_id=ADMIN_TELEGRAM_ID, full_name="Admin Adminov"):
    return User(
        full_name=full_name,
        phone="+998900000000",
        role=Role.ADMIN,
        telegram_user_id=telegram_user_id,
        ID=staff_id,
        clinic_id=1,
        clinic_name="Manual Med",
    )


def _own_scope_staff_repo():
    return FakeStaffRepo({
        ADMIN_TELEGRAM_ID: Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="own"),
    })


def _build_router(user_repo, staff_repo, appointment_repo=None, instance="mm"):
    clinic_repo = FakeClinicRepo(Clinic(clinic_id=1, name="Manual Med", token="t"))
    return create_admin_appointment_creation_router(
        instance, appointment_repo or FakeAppointmentRepository(), user_repo, staff_repo, clinic_repo,
    )


def _find_callback_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"callback handler {name} not found")


def _callback_query(telegram_user_id=ADMIN_TELEGRAM_ID):
    callback_query = MagicMock()
    callback_query.from_user.id = telegram_user_id
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _state(**data):
    state = MagicMock()
    state.get_data = AsyncMock(return_value=data)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


CREATION_NOW_PATCH_TARGET = "bot.handlers.admin.appointment_management.appointment_creation.get_current_tashkent_datetime"


# --- change_calendar_month ---

@pytest.mark.asyncio
async def test_change_calendar_month_moves_to_requested_month_and_stays_in_choose_day():
    admin = _admin()
    router = _build_router(FakeUserRepo(admin=admin), _own_scope_staff_repo())
    change_calendar_month = _find_callback_handler(router, "change_calendar_month")

    callback_query = _callback_query()
    state = _state()

    await change_calendar_month(callback_query, ApptCalendarMonthCB(year=2026, month=8), state, admin)

    state.update_data.assert_awaited_once_with(calendar_year=2026, calendar_month=8)
    state.set_state.assert_awaited_once_with(AppointmentCreationStates.choose_day)
    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == f"📅 {format_month_label(2026, 8)}"
    callback_query.answer.assert_awaited_once()


# --- pick_calendar_day ---

@pytest.mark.asyncio
async def test_pick_calendar_day_with_valid_day_and_no_conflicts_shows_full_slot_grid_and_sets_state():
    admin = _admin()
    router = _build_router(FakeUserRepo(admin=admin), _own_scope_staff_repo())
    pick_calendar_day = _find_callback_handler(router, "pick_calendar_day")

    callback_query = _callback_query()
    state = _state(staff_user_id=admin.ID)

    with patch(CREATION_NOW_PATCH_TARGET, return_value=FIXED_NOW):
        await pick_calendar_day(callback_query, ApptCalendarDayCB(year=2026, month=7, day=8), state, admin)

    state.update_data.assert_awaited_once_with(day_iso="2026-07-08")
    state.set_state.assert_awaited_once_with(AppointmentCreationStates.choose_slot)
    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == "Выберите время на 08.07.2026:"
    expected_occupancy = [(slot, []) for slot in BOOKING_SLOTS]
    assert kwargs["reply_markup"] == appointment_slot_grid_kb(
        expected_occupancy, cancel_callback_data="admin_book_back_to_day"
    )
    callback_query.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_pick_calendar_day_with_fully_booked_day_still_renders_grid_with_occupied_markers():
    """Semantic change from the old week-based day picker: a fully-booked day
    is no longer an alert-and-bail case -- get_day_slot_occupancy always
    returns every generated slot, occupied or not, so the grid renders with
    each slot clickable through to its (read-only) occupant card."""
    admin = _admin()
    day_iso = "2026-07-08"
    fully_booked = [
        Appointment(
            clinic_id=1, client_id=1, doctor_id=admin.ID,
            datetime=f"{day_iso} {slot}", purpose="Consultation",
            created_by=CreatedBy.ADMIN, status=AppointmentStatus.CONFIRMED, id=i,
        )
        for i, slot in enumerate(BOOKING_SLOTS, start=1)
    ]
    appointment_repo = FakeAppointmentRepository(fully_booked)
    router = _build_router(FakeUserRepo(admin=admin), _own_scope_staff_repo(), appointment_repo)
    pick_calendar_day = _find_callback_handler(router, "pick_calendar_day")

    callback_query = _callback_query()
    state = _state(staff_user_id=admin.ID)

    with patch(CREATION_NOW_PATCH_TARGET, return_value=FIXED_NOW):
        await pick_calendar_day(callback_query, ApptCalendarDayCB(year=2026, month=7, day=8), state, admin)

    state.update_data.assert_awaited_once_with(day_iso=day_iso)
    state.set_state.assert_awaited_once_with(AppointmentCreationStates.choose_slot)

    appts_by_slot = {a.datetime.split(" ")[1]: a for a in fully_booked}
    expected_occupancy = [(slot, [appts_by_slot[slot]]) for slot in BOOKING_SLOTS]
    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert kwargs["reply_markup"] == appointment_slot_grid_kb(
        expected_occupancy, cancel_callback_data="admin_book_back_to_day"
    )
    callback_query.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_pick_calendar_day_with_no_remaining_slots_today_shows_alert_and_leaves_state_unchanged():
    admin = _admin()
    router = _build_router(FakeUserRepo(admin=admin), _own_scope_staff_repo())
    pick_calendar_day = _find_callback_handler(router, "pick_calendar_day")

    callback_query = _callback_query()
    state = _state(staff_user_id=admin.ID)
    now_after_hours = datetime(2026, 7, 6, 18, 0)  # mm's WORKING_HOURS_END is 17:00

    with patch(CREATION_NOW_PATCH_TARGET, return_value=now_after_hours):
        await pick_calendar_day(callback_query, ApptCalendarDayCB(year=2026, month=7, day=6), state, admin)

    callback_query.answer.assert_awaited_once_with("На этот день нет доступных слотов.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    state.update_data.assert_not_called()
    state.set_state.assert_not_called()


# --- back_to_day_selection ---

@pytest.mark.asyncio
async def test_back_to_day_selection_returns_to_stored_calendar_month():
    admin = _admin()
    router = _build_router(FakeUserRepo(admin=admin), _own_scope_staff_repo())
    back_to_day_selection = _find_callback_handler(router, "back_to_day_selection")

    callback_query = _callback_query()
    state = _state(calendar_year=2026, calendar_month=8, staff_user_id=admin.ID)

    with patch(CREATION_NOW_PATCH_TARGET, return_value=FIXED_NOW):
        await back_to_day_selection(callback_query, state, admin)

    state.update_data.assert_awaited_once_with(calendar_year=2026, calendar_month=8)
    state.set_state.assert_awaited_once_with(AppointmentCreationStates.choose_day)
    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == f"📅 {format_month_label(2026, 8)}"


@pytest.mark.asyncio
async def test_back_to_day_selection_defaults_to_current_month_when_not_stored():
    admin = _admin()
    router = _build_router(FakeUserRepo(admin=admin), _own_scope_staff_repo())
    back_to_day_selection = _find_callback_handler(router, "back_to_day_selection")

    callback_query = _callback_query()
    state = _state(staff_user_id=admin.ID)

    with patch(CREATION_NOW_PATCH_TARGET, return_value=FIXED_NOW):
        await back_to_day_selection(callback_query, state, admin)

    state.update_data.assert_awaited_once_with(calendar_year=FIXED_NOW.year, calendar_month=FIXED_NOW.month)


# --- view_occupied_slot ---

@pytest.mark.asyncio
async def test_view_occupied_slot_shows_read_only_card():
    admin = _admin()
    occupant = Appointment(
        clinic_id=1, client_id=1, doctor_id=admin.ID,
        datetime="2026-07-08 09:00", purpose="Consultation",
        created_by=CreatedBy.ADMIN, status=AppointmentStatus.CONFIRMED, id=7,
    )
    appointment_repo = FakeAppointmentRepository([occupant])
    router = _build_router(FakeUserRepo(admin=admin), _own_scope_staff_repo(), appointment_repo)
    view_occupied_slot = _find_callback_handler(router, "view_occupied_slot")

    callback_query = _callback_query()
    state = _state()

    await view_occupied_slot(callback_query, AdminOccupiedSlotCB(appointment_id=7), state, admin)

    callback_query.answer.assert_awaited_once_with('')
    callback_query.message.edit_text.assert_awaited_once_with(
        build_appointment_card(occupant),
        reply_markup=occupied_slot_card_kb(),
    )


@pytest.mark.asyncio
async def test_view_occupied_slot_with_missing_appointment_shows_alert():
    admin = _admin()
    router = _build_router(FakeUserRepo(admin=admin), _own_scope_staff_repo(), FakeAppointmentRepository())
    view_occupied_slot = _find_callback_handler(router, "view_occupied_slot")

    callback_query = _callback_query()
    state = _state()

    await view_occupied_slot(callback_query, AdminOccupiedSlotCB(appointment_id=404), state, admin)

    callback_query.answer.assert_awaited_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()


# --- back_to_slot_grid ---

@pytest.mark.asyncio
async def test_back_to_slot_grid_rerenders_the_stored_days_slot_grid():
    admin = _admin()
    router = _build_router(FakeUserRepo(admin=admin), _own_scope_staff_repo())
    back_to_slot_grid = _find_callback_handler(router, "back_to_slot_grid")

    callback_query = _callback_query()
    state = _state(staff_user_id=admin.ID, day_iso="2026-07-08")

    with patch(CREATION_NOW_PATCH_TARGET, return_value=FIXED_NOW):
        await back_to_slot_grid(callback_query, state, admin)

    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == "Выберите время на 08.07.2026:"
    expected_occupancy = [(slot, []) for slot in BOOKING_SLOTS]
    assert kwargs["reply_markup"] == appointment_slot_grid_kb(
        expected_occupancy, cancel_callback_data="admin_book_back_to_day"
    )
    callback_query.answer.assert_awaited_once()


# --- pick_slot ---

@pytest.mark.asyncio
async def test_pick_slot_with_valid_slot_updates_state_with_datetime_and_display_and_moves_to_purpose():
    admin = _admin()
    router = _build_router(FakeUserRepo(admin=admin), _own_scope_staff_repo())
    pick_slot = _find_callback_handler(router, "pick_slot")

    callback_query = _callback_query()
    state = _state(day_iso="2026-07-08")

    await pick_slot(callback_query, ClientBookSlotCB(slot="09:00"), state, admin)

    expected_display = format_datetime_for_display(datetime(2026, 7, 8, 9, 0))
    state.update_data.assert_awaited_once_with(
        slot="09:00",
        appointment_datetime="2026-07-08 09:00",
        appointment_datetime_display=expected_display,
    )
    state.set_state.assert_awaited_once_with(AppointmentCreationStates.purpose)
    # instance="mm" (this file's default router) gets the mm-specific prompt;
    # only instance="zb" sees "Опишите услугу (например: Консультация):".
    callback_query.message.edit_text.assert_awaited_once_with(
        "Опишите боль или проблему:",
        reply_markup=back_to_records_kb(),
    )
    callback_query.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_pick_slot_with_malformed_slot_shows_alert_and_does_not_touch_state():
    admin = _admin()
    router = _build_router(FakeUserRepo(admin=admin), _own_scope_staff_repo())
    pick_slot = _find_callback_handler(router, "pick_slot")

    callback_query = _callback_query()
    state = _state(day_iso="2026-07-08")

    await pick_slot(callback_query, ClientBookSlotCB(slot="xx:yy"), state, admin)

    callback_query.answer.assert_awaited_once_with("Некорректное время, попробуйте ещё раз.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    state.get_data.assert_not_called()
    state.update_data.assert_not_called()
    state.set_state.assert_not_called()


# --- begin_appointment_creation: both instances now enter the calendar ---

def _clinic():
    return Clinic(clinic_id=1, name="Manual Med", token="t")


def _appt_mng_mock(admin_user=None):
    appt_mng = MagicMock()
    appt_mng.get_admin_clinic = AsyncMock(return_value=_clinic())
    appt_mng.list_clinic_doctors_for_creation = AsyncMock(return_value=[])
    appt_mng.get_user_by_telegram_id = AsyncMock(return_value=admin_user)
    return appt_mng


HELPERS_NOW_PATCH_TARGET = "bot.handlers.utils.admin_utils.appointment_helpers.get_current_tashkent_datetime"


@pytest.mark.asyncio
async def test_begin_appointment_creation_zb_slots_mode_enters_calendar_with_admin_fallback_staff_id():
    """zb now runs "slots" mode too (DATEPARSER_BY_INSTANCE["zb"] == "slots"):
    it must enter the calendar month view, not the retired free-text prompt."""
    admin_user = User(
        ID=42, full_name="Admin Adminov", phone="+998900000000", role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1,
    )
    appt_mng = _appt_mng_mock(admin_user=admin_user)
    callback_query = _callback_query()
    state = _state()

    with patch(HELPERS_NOW_PATCH_TARGET, return_value=FIXED_NOW):
        await ah.begin_appointment_creation(
            appt_mng, callback_query, state,
            instance="zb", full_name="Ivanov Ivan", phone="+998901234567",
        )

    appt_mng.get_user_by_telegram_id.assert_awaited_once_with(ADMIN_TELEGRAM_ID)
    update_calls = [call.kwargs for call in state.update_data.await_args_list]
    assert {"staff_user_id": 42} in update_calls
    state.set_state.assert_awaited_once_with(AppointmentCreationStates.choose_day)
    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == f"📅 {format_month_label(FIXED_NOW.year, FIXED_NOW.month)}"


@pytest.mark.asyncio
async def test_begin_appointment_creation_mm_slots_mode_enters_calendar_with_admin_fallback_staff_id():
    """instance="mm" (DATEPARSER_BY_INSTANCE == "slots") must enter the
    calendar month view instead, and -- since no doctor was pre-selected in
    FSM data -- _ensure_staff_user_id must fall back to the acting admin's
    own User.ID, mirroring AppointmentManagement.create_appointment's own
    default."""
    admin_user = User(
        ID=42, full_name="Admin Adminov", phone="+998900000000", role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1,
    )
    appt_mng = _appt_mng_mock(admin_user=admin_user)
    callback_query = _callback_query()
    state = _state()  # no staff_user_id preset

    with patch(HELPERS_NOW_PATCH_TARGET, return_value=FIXED_NOW):
        await ah.begin_appointment_creation(
            appt_mng, callback_query, state,
            instance="mm", full_name="Ivanov Ivan", phone="+998901234567",
        )

    appt_mng.get_user_by_telegram_id.assert_awaited_once_with(ADMIN_TELEGRAM_ID)
    update_calls = [call.kwargs for call in state.update_data.await_args_list]
    assert {"staff_user_id": 42} in update_calls
    state.set_state.assert_awaited_once_with(AppointmentCreationStates.choose_day)
    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == f"📅 {format_month_label(FIXED_NOW.year, FIXED_NOW.month)}"


# --- _ensure_staff_user_id: direct unit coverage ---

@pytest.mark.asyncio
async def test_ensure_staff_user_id_is_noop_when_already_set():
    appt_mng = MagicMock()
    appt_mng.get_user_by_telegram_id = AsyncMock()
    state = _state(staff_user_id=7)

    await ah._ensure_staff_user_id(appt_mng, state, ADMIN_TELEGRAM_ID)

    appt_mng.get_user_by_telegram_id.assert_not_awaited()
    state.update_data.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_staff_user_id_sets_admins_own_id_when_missing():
    admin_user = User(
        ID=42, full_name="Admin Adminov", phone="+998900000000", role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1,
    )
    appt_mng = MagicMock()
    appt_mng.get_user_by_telegram_id = AsyncMock(return_value=admin_user)
    state = _state()

    await ah._ensure_staff_user_id(appt_mng, state, ADMIN_TELEGRAM_ID)

    appt_mng.get_user_by_telegram_id.assert_awaited_once_with(ADMIN_TELEGRAM_ID)
    state.update_data.assert_awaited_once_with(staff_user_id=42)


@pytest.mark.asyncio
async def test_ensure_staff_user_id_noop_when_admin_lookup_returns_none():
    appt_mng = MagicMock()
    appt_mng.get_user_by_telegram_id = AsyncMock(return_value=None)
    state = _state()

    await ah._ensure_staff_user_id(appt_mng, state, ADMIN_TELEGRAM_ID)

    state.update_data.assert_not_called()
