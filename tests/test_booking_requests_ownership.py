"""Card-level ownership check tests for booking_requests.py.

docs/appointment_card_ownership_check_prompt.md: confirm/reject/cancel_propose/
approve_propose_datetime all take a raw appointment_id from callback data and
must reject access outside the admin resolved clinic/doctor scope through
AppointmentManagement.get_appointment_for_admin, independently of the
service-level coverage in test_appointment_management.py.

Note: start_propose_datetime is out of scope by explicit user decision -- it
only opens a UI step (no read/mutation of the appointment), see the prompt
doc's carried-forward reviewer note.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.admin.appointment_management.booking_requests import (
    create_admin_booking_requests_router,
)
from bot.keyboards.admin.record_management_kb.booking_request_cb import BookingRequestActionCB
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


OWN_ADMIN_TELEGRAM_ID = 999
OWN_ADMIN_ID = 1
OTHER_DOCTOR_ID = 2
CLINIC_ADMIN_TELEGRAM_ID = 2000
CLINIC_ADMIN_ID = 3
MISSING_ADMIN_TELEGRAM_ID = 4000

FOREIGN_APPOINTMENT_ID = 10
OTHER_CLINIC_APPOINTMENT_ID = 11
NONEXISTENT_APPOINTMENT_ID = 999


class FakeAppointmentRepository:
    def __init__(self, appointments):
        self.appointments = list(appointments)
        self.status_updates = []
        self.proposed_datetime_updates = []
        self.proposed_by_updates = []

    async def get_appointment_by_id(self, appointment_id):
        return next((a for a in self.appointments if a.id == appointment_id), None)

    async def get_appointments_by_doctor_and_date(self, doctor_id, date):
        return [
            a for a in self.appointments
            if a.doctor_id == doctor_id and a.datetime.startswith(date) and a.status == AppointmentStatus.CONFIRMED
        ]

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.status_updates.append((appointment_id, status))

    async def update_proposed_datetime(self, appointment_id, proposed_datetime):
        self.proposed_datetime_updates.append((appointment_id, proposed_datetime))

    async def update_proposed_by(self, appointment_id, proposed_by):
        self.proposed_by_updates.append((appointment_id, proposed_by))


class FakeUserRepo:
    def __init__(self, users_by_telegram_id):
        self.users = users_by_telegram_id

    async def get_user_by_telegram_id(self, telegram_user_id):
        return self.users.get(telegram_user_id)


class FakeStaffRepo:
    def __init__(self, staff_by_telegram_id):
        self.staff = staff_by_telegram_id

    async def get_staff(self, telegram_user_id):
        return self.staff.get(telegram_user_id)


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
        ID=OWN_ADMIN_ID,
        clinic_id=1,
        clinic_name="Zub Mudrosti",
        visibility_scope="own",
    )


def _clinic_admin():
    return User(
        full_name="Ivanova Irina",
        phone="+998901112233",
        role=Role.ADMIN,
        telegram_user_id=CLINIC_ADMIN_TELEGRAM_ID,
        ID=CLINIC_ADMIN_ID,
        clinic_id=1,
        clinic_name="Zub Mudrosti",
        visibility_scope="clinic",
    )


def _foreign_booking_request(status=AppointmentStatus.PENDING):
    """Same clinic as the own-scope admin, but a different doctor."""
    return Appointment(
        clinic_id=1,
        client_id=7,
        doctor_id=OTHER_DOCTOR_ID,
        datetime="2026-08-01 10:00",
        purpose="Bolit zub",
        created_by=CreatedBy.CLIENT,
        status=status,
        id=FOREIGN_APPOINTMENT_ID,
    )


def _other_clinic_booking_request(status=AppointmentStatus.PENDING):
    return Appointment(
        clinic_id=2,
        client_id=7,
        doctor_id=OTHER_DOCTOR_ID,
        datetime="2026-08-01 10:00",
        purpose="Bolit zub",
        created_by=CreatedBy.CLIENT,
        status=status,
        id=OTHER_CLINIC_APPOINTMENT_ID,
    )


def _build_router(appointment_repo, admins=None):
    admins = admins or {OWN_ADMIN_TELEGRAM_ID: _own_admin(), CLINIC_ADMIN_TELEGRAM_ID: _clinic_admin()}
    user_repo = FakeUserRepo(admins)
    staff_repo = FakeStaffRepo({
        OWN_ADMIN_TELEGRAM_ID: Staff(telegram_user_id=OWN_ADMIN_TELEGRAM_ID, clinic_id=1),
        CLINIC_ADMIN_TELEGRAM_ID: Staff(telegram_user_id=CLINIC_ADMIN_TELEGRAM_ID, clinic_id=1),
    })
    clinic_repo = FakeClinicRepo({1: Clinic(clinic_id=1, name="Zub Mudrosti", token="t")})
    return create_admin_booking_requests_router(appointment_repo, user_repo, staff_repo, clinic_repo)


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _callback_query(telegram_user_id=OWN_ADMIN_TELEGRAM_ID):
    callback_query = MagicMock()
    callback_query.from_user.id = telegram_user_id
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _state(**data):
    state = MagicMock()
    state.get_data = AsyncMock(return_value=data)
    state.clear = AsyncMock()
    return state


# --- confirm_request ---

@pytest.mark.asyncio
async def test_confirm_request_denies_own_scope_admin_for_other_doctor_appointment():
    appt_repo = FakeAppointmentRepository([_foreign_booking_request()])
    router = _build_router(appt_repo)
    confirm_request = _find_handler(router, "confirm_request")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    callback_data = BookingRequestActionCB(action="confirm", appointment_id=FOREIGN_APPOINTMENT_ID)

    await confirm_request(callback_query, callback_data)

    callback_query.answer.assert_called_once_with("Заявка не найдена", show_alert=True)
    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_confirm_request_denies_clinic_scope_admin_for_other_clinic_appointment():
    appt_repo = FakeAppointmentRepository([_other_clinic_booking_request()])
    router = _build_router(appt_repo)
    confirm_request = _find_handler(router, "confirm_request")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    callback_data = BookingRequestActionCB(action="confirm", appointment_id=OTHER_CLINIC_APPOINTMENT_ID)

    await confirm_request(callback_query, callback_data)

    callback_query.answer.assert_called_once_with("Заявка не найдена", show_alert=True)
    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_confirm_request_foreign_and_nonexistent_ids_give_identical_response():
    appt_repo = FakeAppointmentRepository([_foreign_booking_request()])
    router = _build_router(appt_repo)
    confirm_request = _find_handler(router, "confirm_request")

    foreign_cb = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    await confirm_request(
        foreign_cb, BookingRequestActionCB(action="confirm", appointment_id=FOREIGN_APPOINTMENT_ID),
    )

    missing_cb = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    await confirm_request(
        missing_cb, BookingRequestActionCB(action="confirm", appointment_id=NONEXISTENT_APPOINTMENT_ID),
    )

    assert foreign_cb.answer.call_args == missing_cb.answer.call_args


@pytest.mark.asyncio
async def test_confirm_request_denies_when_admin_user_missing():
    appt_repo = FakeAppointmentRepository([_foreign_booking_request()])
    router = _build_router(appt_repo)
    confirm_request = _find_handler(router, "confirm_request")

    callback_query = _callback_query(MISSING_ADMIN_TELEGRAM_ID)
    callback_data = BookingRequestActionCB(action="confirm", appointment_id=FOREIGN_APPOINTMENT_ID)

    await confirm_request(callback_query, callback_data)

    callback_query.answer.assert_called_once_with("Заявка не найдена", show_alert=True)
    assert appt_repo.status_updates == []


# --- reject_request ---

@pytest.mark.asyncio
async def test_reject_request_denies_own_scope_admin_for_other_doctor_appointment():
    appt_repo = FakeAppointmentRepository([_foreign_booking_request()])
    router = _build_router(appt_repo)
    reject_request = _find_handler(router, "reject_request")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    callback_data = BookingRequestActionCB(action="reject", appointment_id=FOREIGN_APPOINTMENT_ID)

    await reject_request(callback_query, callback_data)

    callback_query.answer.assert_called_once_with("Заявка не найдена", show_alert=True)
    assert appt_repo.status_updates == []


# --- cancel_propose ---

@pytest.mark.asyncio
async def test_cancel_propose_denies_own_scope_admin_for_other_doctor_appointment():
    appt_repo = FakeAppointmentRepository([_foreign_booking_request()])
    router = _build_router(appt_repo)
    cancel_propose = _find_handler(router, "cancel_propose")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    callback_data = BookingRequestActionCB(action="cancel_propose", appointment_id=FOREIGN_APPOINTMENT_ID)

    await cancel_propose(callback_query, callback_data, _state())

    callback_query.answer.assert_called_once_with("Заявка не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()


# --- approve_propose_datetime ---

@pytest.mark.asyncio
async def test_approve_propose_datetime_denies_own_scope_admin_for_other_doctor_appointment():
    appt_repo = FakeAppointmentRepository([_foreign_booking_request()])
    router = _build_router(appt_repo)
    approve_propose_datetime = _find_handler(router, "approve_propose_datetime")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    callback_data = BookingRequestActionCB(
        action="approve_propose_datetime", appointment_id=FOREIGN_APPOINTMENT_ID,
    )
    state = _state(
        appointment_datetime_parsed=datetime(2026, 8, 5, 12, 0),
        appointment_datetime_display="05.08.2026 12:00",
    )

    await approve_propose_datetime(callback_query, callback_data, state)

    callback_query.answer.assert_called_once_with("Заявка не найдена", show_alert=True)
    assert appt_repo.proposed_datetime_updates == []
    assert appt_repo.proposed_by_updates == []
