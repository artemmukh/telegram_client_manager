"""Handler-level tests for reschedule_requests.py's calendar+slot-picker
counter-propose flow (Phase D): mirrors booking_requests.py's equivalent
flow (see test_booking_requests_calendar_slot_picker.py) but scoped to
RescheduleRequestStates.choose_day/choose_slot, admin counter-proposing a
new time over a client's reschedule request.

Covers: start_propose_datetime's branch on DATA_PARSE_MODE.get(instance),
pick_propose_calendar_day (including the exclude_appointment_id behavior new
to this flow -- the appointment's own current slot must not render as
occupied), pick_propose_slot, the back-navigation chain, and an integration
test proving the untouched approve_propose_datetime handler still works
correctly on the FSM data the new slot picker produces.

Follows the direct-handler-call/fake-repository convention established in
test_appointment_creation_mm_slot_picker.py / test_reschedule_requests_propose_handler.py.
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config.booking_config import BOOKING_SLOTS
from bot.handlers.utils.admin_utils.appointment_calendar_helpers import format_month_label
from bot.handlers.admin.appointment_management.reschedule_requests import (
    create_admin_reschedule_requests_router,
)
from bot.handlers.utils.admin_utils.appointment_helpers import build_appointment_card
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import ApptCalendarDayCB
from bot.keyboards.admin.record_management_kb.appointment_creation_cb import AdminOccupiedSlotCB
from bot.keyboards.admin.record_management_kb.appointment_slot_kb import appointment_slot_grid_kb, occupied_slot_card_kb
from bot.keyboards.admin.record_management_kb.reschedule_request_cb import RescheduleRequestActionCB
from bot.keyboards.admin.record_management_kb.reschedule_request_kb import (
    reschedule_request_confirm_propose_kb,
    reschedule_request_propose_cancel_kb,
)
from bot.keyboards.client.booking_cb import ClientBookSlotCB
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.services.utils.date_parser import format_datetime_for_confirmation
from bot.states.admin.record_management.reschedule_request_states import RescheduleRequestStates
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role

ADMIN_TELEGRAM_ID = 999
DOCTOR_ID = 55
FIXED_NOW = datetime(2026, 7, 6, 9, 0)  # a Monday, matching test_appointment_creation_mm_slot_picker.py
NOW_PATCH_TARGET = "bot.handlers.admin.appointment_management.reschedule_requests.get_current_tashkent_datetime"


class FakeAppointmentRepository:
    def __init__(self, appointment, other_appointments=None):
        self.appointment = appointment
        self.other_appointments = list(other_appointments or [])
        self.proposed_datetime_updates = []
        self.proposed_by_updates = []
        self.notification_message_id_updates = []

    async def get_appointment_by_id(self, appointment_id):
        if appointment_id == self.appointment.id:
            return self.appointment
        return next((a for a in self.other_appointments if a.id == appointment_id), None)

    async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None):
        pool = [self.appointment, *self.other_appointments]
        matches = [a for a in pool if a.doctor_id == doctor_id and a.datetime.startswith(date)]
        if statuses is not None:
            matches = [a for a in matches if a.status in statuses]
        return matches

    async def update_proposed_datetime(self, appointment_id, proposed_datetime):
        self.proposed_datetime_updates.append((appointment_id, proposed_datetime))
        self.appointment.proposed_datetime = proposed_datetime

    async def update_proposed_by(self, appointment_id, proposed_by):
        self.proposed_by_updates.append((appointment_id, proposed_by))
        self.appointment.proposed_by = proposed_by

    async def update_notification_message_id(self, appointment_id, message_id):
        self.notification_message_id_updates.append((appointment_id, message_id))

    async def try_propose_new_datetime(
        self, appointment_id, new_datetime, decided_by_user_id, status_updated_at, expected_status
    ):
        if self.appointment.status.value != expected_status:
            return False
        self.proposed_datetime_updates.append((appointment_id, None))
        self.proposed_by_updates.append((appointment_id, None))
        return True

    async def try_apply_new_datetime_immediately(
        self, appointment_id, new_datetime, decided_by_user_id, status_updated_at, expected_status
    ):
        if self.appointment.status.value != expected_status:
            return False
        if self.appointment.proposed_datetime is not None and self.appointment.proposed_by == CreatedBy.ADMIN:
            return False
        self.proposed_datetime_updates.append((appointment_id, None))
        self.proposed_by_updates.append((appointment_id, None))
        return True


class FakeUserRepo:
    def __init__(self, client=None):
        self.client = client

    async def get_user_by_telegram_id(self, telegram_user_id):
        return User(
            full_name="Петров Петр",
            phone="+998907654321",
            role=Role.ADMIN,
            telegram_user_id=ADMIN_TELEGRAM_ID,
            ID=1,
            clinic_id=1,
            clinic_name="Зуб Мудрости",
        )

    async def get_client_by_id(self, user_id):
        return self.client


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=1, visibility_scope="clinic")


class FakeClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=1, name="Зуб Мудрости", token="t")


def _confirmed_appointment(day_iso="2026-08-15", slot="09:00", appointment_id=1):
    return Appointment(
        clinic_id=1,
        client_id=7,
        doctor_id=DOCTOR_ID,
        datetime=f"{day_iso} {slot}",
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=AppointmentStatus.CONFIRMED,
        id=appointment_id,
    )


def _build_router(appt_repo, instance="zb", notification_service=None, appointment_scheduler=None):
    return create_admin_reschedule_requests_router(
        instance, appt_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service, appointment_scheduler=appointment_scheduler,
    )


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
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


def _admin_user():
    return User(
        full_name="Петров Петр", phone="+998907654321", role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID, ID=1, clinic_id=1, clinic_name="Зуб Мудрости",
    )


# --- start_propose_datetime: branch on DATA_PARSE_MODE ---

@pytest.mark.asyncio
async def test_start_propose_datetime_slots_mode_enters_calendar_and_stashes_staff_and_old_datetime():
    appointment = _confirmed_appointment()
    router = _build_router(FakeAppointmentRepository(appointment))
    start_propose_datetime = _find_handler(router, "start_propose_datetime")

    callback_query = _callback_query()
    state = _state()

    with patch(NOW_PATCH_TARGET, return_value=FIXED_NOW):
        await start_propose_datetime(
            callback_query, RescheduleRequestActionCB(action="propose", appointment_id=1), state, _admin_user(),
        )

    update_calls = [call.kwargs for call in state.update_data.await_args_list]
    assert {"appointment_id": 1} in update_calls
    assert {"staff_user_id": DOCTOR_ID, "old_datetime": "2026-08-15 09:00"} in update_calls
    state.set_state.assert_awaited_once_with(RescheduleRequestStates.choose_day)
    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == f"📅 {format_month_label(FIXED_NOW.year, FIXED_NOW.month)}"


@pytest.mark.asyncio
async def test_start_propose_datetime_missing_appointment_shows_alert_and_does_not_enter_calendar():
    appointment = _confirmed_appointment()
    router = _build_router(FakeAppointmentRepository(appointment))
    start_propose_datetime = _find_handler(router, "start_propose_datetime")

    callback_query = _callback_query()
    state = _state()

    await start_propose_datetime(
        callback_query, RescheduleRequestActionCB(action="propose", appointment_id=404), state, _admin_user(),
    )

    callback_query.answer.assert_awaited_once_with("Заявка не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_start_propose_datetime_non_slots_mode_still_uses_free_text_prompt():
    appointment = _confirmed_appointment()
    router = _build_router(FakeAppointmentRepository(appointment), instance="legacy_instance")
    start_propose_datetime = _find_handler(router, "start_propose_datetime")

    callback_query = _callback_query()
    state = _state()

    await start_propose_datetime(
        callback_query, RescheduleRequestActionCB(action="propose", appointment_id=1), state, _admin_user(),
    )

    state.set_state.assert_awaited_once_with(RescheduleRequestStates.new_datetime)
    callback_query.message.edit_text.assert_awaited_once_with(
        "Введите новую дату и время (например: завтра в 15:00):",
        reply_markup=reschedule_request_propose_cancel_kb(1),
    )


# --- pick_propose_calendar_day ---

@pytest.mark.asyncio
async def test_pick_propose_calendar_day_excludes_the_appointments_own_current_slot_from_occupied_markers():
    day_iso = "2026-08-15"
    appointment = _confirmed_appointment(day_iso=day_iso, slot="09:00", appointment_id=1)
    other_occupant = Appointment(
        clinic_id=1, client_id=9, doctor_id=DOCTOR_ID,
        datetime=f"{day_iso} 10:00", purpose="Осмотр",
        created_by=CreatedBy.ADMIN, status=AppointmentStatus.CONFIRMED, id=2,
    )
    appt_repo = FakeAppointmentRepository(appointment, other_appointments=[other_occupant])
    router = _build_router(appt_repo)
    pick_propose_calendar_day = _find_handler(router, "pick_propose_calendar_day")

    callback_query = _callback_query()
    state = _state(appointment_id=1, staff_user_id=DOCTOR_ID, old_datetime=f"{day_iso} 09:00")

    with patch(NOW_PATCH_TARGET, return_value=FIXED_NOW):
        await pick_propose_calendar_day(
            callback_query, ApptCalendarDayCB(year=2026, month=8, day=15), state, _admin_user(),
        )

    state.update_data.assert_awaited_once_with(day_iso=day_iso)
    state.set_state.assert_awaited_once_with(RescheduleRequestStates.choose_slot)

    expected_occupancy = [
        (slot, [other_occupant] if slot == "10:00" else [])
        for slot in BOOKING_SLOTS
    ]
    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == "Выберите время на 15.08.2026:"
    assert kwargs["reply_markup"] == appointment_slot_grid_kb(
        expected_occupancy, cancel_callback_data="admin_book_back_to_day"
    )
    callback_query.answer.assert_awaited_once()


# --- back navigation chain ---

@pytest.mark.asyncio
async def test_back_to_propose_day_selection_returns_to_month_grid_not_full_reset():
    appointment = _confirmed_appointment()
    router = _build_router(FakeAppointmentRepository(appointment))
    back_to_propose_day_selection = _find_handler(router, "back_to_propose_day_selection")

    callback_query = _callback_query()
    state = _state(appointment_id=1, calendar_year=2026, calendar_month=8)

    with patch(NOW_PATCH_TARGET, return_value=FIXED_NOW):
        await back_to_propose_day_selection(callback_query, state, _admin_user())

    state.update_data.assert_awaited_once_with(calendar_year=2026, calendar_month=8)
    state.set_state.assert_awaited_once_with(RescheduleRequestStates.choose_day)
    state.clear.assert_not_called()


@pytest.mark.asyncio
async def test_view_propose_occupied_slot_then_back_returns_to_slot_grid_not_full_reset():
    day_iso = "2026-08-15"
    appointment = _confirmed_appointment(day_iso=day_iso, slot="09:00", appointment_id=1)
    occupant = Appointment(
        clinic_id=1, client_id=9, doctor_id=DOCTOR_ID,
        datetime=f"{day_iso} 10:00", purpose="Осмотр",
        created_by=CreatedBy.ADMIN, status=AppointmentStatus.CONFIRMED, id=2,
    )
    appt_repo = FakeAppointmentRepository(appointment, other_appointments=[occupant])
    router = _build_router(appt_repo)
    view_propose_occupied_slot = _find_handler(router, "view_propose_occupied_slot")
    back_to_propose_slot_grid = _find_handler(router, "back_to_propose_slot_grid")

    callback_query = _callback_query()
    state = _state(appointment_id=1, staff_user_id=DOCTOR_ID, day_iso=day_iso)

    await view_propose_occupied_slot(callback_query, AdminOccupiedSlotCB(appointment_id=2), state, _admin_user())

    callback_query.message.edit_text.assert_awaited_once_with(
        build_appointment_card(occupant),
        reply_markup=occupied_slot_card_kb(),
    )
    state.clear.assert_not_called()
    state.set_state.assert_not_called()

    callback_query2 = _callback_query()
    with patch(NOW_PATCH_TARGET, return_value=FIXED_NOW):
        await back_to_propose_slot_grid(callback_query2, state, _admin_user())

    state.set_state.assert_awaited_once_with(RescheduleRequestStates.choose_slot)
    args, kwargs = callback_query2.message.edit_text.await_args
    assert "Выберите время на" in args[0]


# --- pick_propose_slot ---

@pytest.mark.asyncio
async def test_pick_propose_slot_writes_parsed_datetime_and_display_then_moves_to_confirm_state():
    day_iso = "2026-08-15"
    appointment = _confirmed_appointment(day_iso=day_iso, slot="09:00", appointment_id=1)
    router = _build_router(FakeAppointmentRepository(appointment))
    pick_propose_slot = _find_handler(router, "pick_propose_slot")

    callback_query = _callback_query()
    state = _state(appointment_id=1, day_iso=day_iso, old_datetime=f"{day_iso} 09:00")

    await pick_propose_slot(callback_query, ClientBookSlotCB(slot="11:00"), state, _admin_user())

    expected_display = format_datetime_for_confirmation(datetime(2026, 8, 15, 11, 0))
    state.update_data.assert_awaited_once_with(
        appointment_datetime_parsed=datetime(2026, 8, 15, 11, 0),
        appointment_datetime_display=expected_display,
    )
    state.set_state.assert_awaited_once_with(RescheduleRequestStates.confirm_new_datetime)

    old_display = format_datetime_for_confirmation(datetime(2026, 8, 15, 9, 0))
    callback_query.message.edit_text.assert_awaited_once_with(
        f"Предложить клиенту время: {old_display} → {expected_display}?",
        reply_markup=reschedule_request_confirm_propose_kb(1),
    )
    callback_query.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_pick_propose_slot_with_malformed_slot_shows_alert_and_does_not_touch_state():
    appointment = _confirmed_appointment()
    router = _build_router(FakeAppointmentRepository(appointment))
    pick_propose_slot = _find_handler(router, "pick_propose_slot")

    callback_query = _callback_query()
    state = _state(appointment_id=1, day_iso="2026-08-15", old_datetime="2026-08-15 09:00")

    await pick_propose_slot(callback_query, ClientBookSlotCB(slot="not-a-time"), state, _admin_user())

    callback_query.answer.assert_awaited_once_with("Некорректное время, попробуйте ещё раз.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    state.update_data.assert_not_called()
    state.set_state.assert_not_called()


# --- integration: new entry path -> untouched approve_propose_datetime exit path ---

@pytest.mark.asyncio
async def test_pick_propose_slot_then_approve_propose_datetime_commits_the_picked_slot():
    day_iso = "2026-08-15"
    appointment = _confirmed_appointment(day_iso=day_iso, slot="09:00", appointment_id=1)
    appt_repo = FakeAppointmentRepository(appointment)

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()

    notification_service = MagicMock()
    notification_service.notify_client_appointment_with_buttons = AsyncMock(return_value=321)

    router = _build_router(
        appt_repo, notification_service=notification_service, appointment_scheduler=appointment_scheduler,
    )
    pick_propose_slot = _find_handler(router, "pick_propose_slot")
    approve_propose_datetime = _find_handler(router, "approve_propose_datetime")

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key=(1, ADMIN_TELEGRAM_ID))
    await state.update_data(appointment_id=1, day_iso=day_iso, old_datetime=f"{day_iso} 09:00")

    callback_query = _callback_query()
    await pick_propose_slot(callback_query, ClientBookSlotCB(slot="11:00"), state, _admin_user())

    approve_callback_query = _callback_query()
    await approve_propose_datetime(
        approve_callback_query, RescheduleRequestActionCB(action="approve_propose_datetime", appointment_id=1), state,
        _admin_user(),
    )

    assert appointment.status is AppointmentStatus.PENDING
    assert appointment.datetime == "2026-08-15 11:00"
    appointment_scheduler.resync_appointment_jobs.assert_awaited_once()
    notification_service.notify_client_appointment_with_buttons.assert_awaited_once()
