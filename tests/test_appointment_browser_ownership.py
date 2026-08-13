"""Card-level ownership check tests for appointment_browser.py.

docs/appointment_card_ownership_check_prompt.md: every handler that reads or
mutates a specific appointment via a raw appointment_id from callback data
must reject access outside the admin resolved clinic/doctor scope through
AppointmentManagement.get_appointment_for_admin -- not just at the service
level (already covered by test_appointment_management.py), but independently
per handler, since each wraps its own call site.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.admin.appointment_management.appointment_browser import (
    create_admin_appointment_browser_router,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import (
    ApptActionCB,
    ApptCardCB,
)
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
    """List-based fake: unlike the single-appointment fakes used elsewhere in
    this test suite, this one can express appointment does not exist at all
    (needed for the identical-response DoD check)."""

    def __init__(self, appointments):
        self.appointments = list(appointments)
        self.status_updates = []
        self.updated = []
        self.price_updates = []
        self.proposed_datetime_updates = []
        self.proposed_by_updates = []
        self.deleted = []

    async def get_appointment_by_id(self, appointment_id):
        return next((a for a in self.appointments if a.id == appointment_id), None)

    async def get_appointments_by_doctor_and_date(self, doctor_id, date):
        return [
            a for a in self.appointments
            if a.doctor_id == doctor_id and a.datetime.startswith(date) and a.status == AppointmentStatus.CONFIRMED
        ]

    async def get_appointment_notification(self, appointment_id, chat_id, message_id, kind):
        return None

    async def appointment_exists(self, appointment_id):
        return any(a.id == appointment_id for a in self.appointments)

    async def delete_appointment(self, appointment_id):
        self.deleted.append(appointment_id)
        self.appointments = [a for a in self.appointments if a.id != appointment_id]

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.status_updates.append((appointment_id, status))

    async def update_appointment(self, appointment_id, appointment):
        self.updated.append((appointment_id, appointment))

    async def update_appointment_price(self, appointment_id, price):
        self.price_updates.append((appointment_id, price))

    async def update_proposed_datetime(self, appointment_id, proposed_datetime):
        self.proposed_datetime_updates.append((appointment_id, proposed_datetime))

    async def update_proposed_by(self, appointment_id, proposed_by):
        self.proposed_by_updates.append((appointment_id, proposed_by))

    async def count_appointments_by_status(self, status, clinic_id, doctor_id=None, tab_bucket=False):
        return len([a for a in self.appointments if a.clinic_id == clinic_id and a.status == status])

    async def get_appointments_by_status_page(self, status, page, clinic_id, doctor_id, per_page, tab_bucket=False):
        return [a for a in self.appointments if a.clinic_id == clinic_id and a.status == status]


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
    )


def _foreign_appointment(status=AppointmentStatus.CONFIRMED):
    """Same clinic as the own-scope admin, but a different doctor."""
    return Appointment(
        clinic_id=1,
        client_id=7,
        doctor_id=OTHER_DOCTOR_ID,
        datetime="2026-08-01 10:00",
        purpose="Konsultatsiya",
        created_by=CreatedBy.ADMIN,
        status=status,
        id=FOREIGN_APPOINTMENT_ID,
    )


def _other_clinic_appointment(status=AppointmentStatus.CONFIRMED):
    """Different clinic entirely; must be blocked even for a clinic-scope admin."""
    return Appointment(
        clinic_id=2,
        client_id=7,
        doctor_id=OTHER_DOCTOR_ID,
        datetime="2026-08-01 10:00",
        purpose="Konsultatsiya",
        created_by=CreatedBy.ADMIN,
        status=status,
        id=OTHER_CLINIC_APPOINTMENT_ID,
    )


def _build_router(appointment_repo, admins=None, appointment_scheduler=None, notification_service=None):
    admins = admins or {OWN_ADMIN_TELEGRAM_ID: _own_admin(), CLINIC_ADMIN_TELEGRAM_ID: _clinic_admin()}
    user_repo = FakeUserRepo(admins)
    staff_repo = FakeStaffRepo({
        OWN_ADMIN_TELEGRAM_ID: Staff(telegram_user_id=OWN_ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="own"),
        CLINIC_ADMIN_TELEGRAM_ID: Staff(telegram_user_id=CLINIC_ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="clinic"),
    })
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


def _callback_query(telegram_user_id=OWN_ADMIN_TELEGRAM_ID):
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


# --- open_card (render_card) ---

@pytest.mark.asyncio
async def test_open_card_denies_own_scope_admin_for_other_doctor_appointment():
    appt_repo = FakeAppointmentRepository([_foreign_appointment()])
    router = _build_router(appt_repo)
    open_card = _find_handler(router, "open_card")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    callback_data = ApptCardCB(appointment_id=FOREIGN_APPOINTMENT_ID, mode="list", page=1)

    await open_card(callback_query, callback_data, _state(), _own_admin())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_open_card_foreign_and_nonexistent_ids_give_identical_response():
    appt_repo = FakeAppointmentRepository([_foreign_appointment()])
    router = _build_router(appt_repo)
    open_card = _find_handler(router, "open_card")

    foreign_cb = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    await open_card(
        foreign_cb, ApptCardCB(appointment_id=FOREIGN_APPOINTMENT_ID, mode="list", page=1), _state(), _own_admin(),
    )

    missing_cb = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    await open_card(
        missing_cb, ApptCardCB(appointment_id=NONEXISTENT_APPOINTMENT_ID, mode="list", page=1), _state(), _own_admin(),
    )

    assert foreign_cb.answer.call_args == missing_cb.answer.call_args
    foreign_cb.message.edit_text.assert_not_called()
    missing_cb.message.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_open_card_denies_when_admin_user_missing():
    appt_repo = FakeAppointmentRepository([_foreign_appointment()])
    router = _build_router(appt_repo)
    open_card = _find_handler(router, "open_card")

    callback_query = _callback_query(MISSING_ADMIN_TELEGRAM_ID)
    callback_data = ApptCardCB(appointment_id=FOREIGN_APPOINTMENT_ID, mode="list", page=1)

    await open_card(callback_query, callback_data, _state(), _own_admin())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()


# --- set_status ---

@pytest.mark.asyncio
async def test_set_status_denies_own_scope_admin_for_other_doctor_appointment():
    appt_repo = FakeAppointmentRepository([_foreign_appointment()])
    router = _build_router(appt_repo)
    set_status = _find_handler(router, "set_status")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    callback_data = ApptActionCB(
        action="set_status", appointment_id=FOREIGN_APPOINTMENT_ID, mode="list", page=1, value="cancelled",
    )

    await set_status(callback_query, callback_data, _state(), _own_admin())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_set_status_denies_clinic_scope_admin_for_other_clinic_appointment():
    appt_repo = FakeAppointmentRepository([_other_clinic_appointment()])
    router = _build_router(appt_repo)
    set_status = _find_handler(router, "set_status")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    callback_data = ApptActionCB(
        action="set_status", appointment_id=OTHER_CLINIC_APPOINTMENT_ID, mode="list", page=1, value="cancelled",
    )

    await set_status(callback_query, callback_data, _state(), _clinic_admin())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    assert appt_repo.status_updates == []


# --- delete (start_delete / finish_delete via confirm_delete_silent) ---

@pytest.mark.asyncio
async def test_start_delete_denies_own_scope_admin_for_other_doctor_appointment():
    appt_repo = FakeAppointmentRepository([_foreign_appointment()])
    router = _build_router(appt_repo)
    start_delete = _find_handler(router, "start_delete")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    callback_data = ApptActionCB(action="delete", appointment_id=FOREIGN_APPOINTMENT_ID, mode="list", page=1)

    await start_delete(callback_query, callback_data, _state(), _own_admin())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_finish_delete_denies_own_scope_admin_for_other_doctor_appointment():
    appt_repo = FakeAppointmentRepository([_foreign_appointment()])
    router = _build_router(appt_repo)
    confirm_delete_silent = _find_handler(router, "confirm_delete_silent")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    callback_data = ApptActionCB(
        action="confirm_delete_silent", appointment_id=FOREIGN_APPOINTMENT_ID, mode="list", page=1,
    )

    await confirm_delete_silent(callback_query, callback_data, _state(), _own_admin())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    assert appt_repo.deleted == []
    assert FOREIGN_APPOINTMENT_ID in [a.id for a in appt_repo.appointments]


# --- edit datetime (approve_new_datetime) ---

@pytest.mark.asyncio
async def test_approve_new_datetime_denies_own_scope_admin_for_other_doctor_appointment():
    from datetime import datetime

    appt_repo = FakeAppointmentRepository([_foreign_appointment()])
    router = _build_router(appt_repo)
    approve_new_datetime = _find_handler(router, "approve_new_datetime")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    callback_data = ApptActionCB(
        action="approve_new_datetime", appointment_id=FOREIGN_APPOINTMENT_ID, mode="list", page=1,
    )
    state = _state(
        appointment_datetime_parsed=datetime(2026, 8, 5, 12, 0),
        appointment_datetime_display="05.08.2026 12:00",
    )

    await approve_new_datetime(callback_query, callback_data, state, _own_admin())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    assert appt_repo.proposed_datetime_updates == []
    assert appt_repo.proposed_by_updates == []


# --- edit purpose (approve_new_purpose) ---

@pytest.mark.asyncio
async def test_approve_new_purpose_denies_own_scope_admin_for_other_doctor_appointment():
    appt_repo = FakeAppointmentRepository([_foreign_appointment()])
    router = _build_router(appt_repo)
    approve_new_purpose = _find_handler(router, "approve_new_purpose")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    callback_data = ApptActionCB(
        action="approve_new_purpose", appointment_id=FOREIGN_APPOINTMENT_ID, mode="list", page=1,
    )

    await approve_new_purpose(callback_query, callback_data, _state(purpose="Osmotr"), _own_admin())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    assert appt_repo.updated == []


# --- edit price (approve_new_price) ---

@pytest.mark.asyncio
async def test_approve_new_price_denies_own_scope_admin_for_other_doctor_appointment():
    appt_repo = FakeAppointmentRepository([_foreign_appointment()])
    router = _build_router(appt_repo)
    approve_new_price = _find_handler(router, "approve_new_price")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    callback_data = ApptActionCB(
        action="approve_new_price", appointment_id=FOREIGN_APPOINTMENT_ID, mode="list", page=1,
    )

    await approve_new_price(callback_query, callback_data, _state(price=150000.0), _own_admin())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    assert appt_repo.price_updates == []


# --- finish_appointment ---

@pytest.mark.asyncio
async def test_finish_appointment_denies_own_scope_admin_for_other_doctor_appointment():
    appt_repo = FakeAppointmentRepository([_foreign_appointment()])
    router = _build_router(appt_repo)
    finish_appointment = _find_handler(router, "finish_appointment")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    callback_data = ApptActionCB(
        action="finish_appointment", appointment_id=FOREIGN_APPOINTMENT_ID, mode="list", page=1,
    )

    await finish_appointment(callback_query, callback_data, _state(), _own_admin())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    assert appt_repo.status_updates == []


# --- doctor-filter picker never shown to doctors ---

@pytest.mark.asyncio
async def test_search_all_renders_list_directly_for_doctor_without_picker():
    """A doctor (own-scope admin) must never see the doctor-filter picker
    added on top of search_all/approve_search -- list_clinic_doctors_for_filter
    always returns [] for own/None-scope callers (see
    test_appointment_browser_doctor_filter.py for the dedicated picker
    coverage), so search_all must render the category list directly, exactly
    as it did before that feature existed."""
    appt_repo = FakeAppointmentRepository([_foreign_appointment(status=AppointmentStatus.CONFIRMED)])
    router = _build_router(appt_repo)
    search_all = _find_handler(router, "search_all")

    callback_query = _callback_query(OWN_ADMIN_TELEGRAM_ID)
    state = _state()

    await search_all(callback_query, state, _own_admin())

    state.set_state.assert_not_called()
    callback_query.message.edit_text.assert_called_once()
    args, _ = callback_query.message.edit_text.call_args
    assert "Выберите врача" not in args[0]
    assert "📒 Все записи" in args[0]


# --- scheduler job migration: finish_delete and finish_appointment must resync/
# cancel through the scheduler's single-source-of-truth methods, not the old
# ad-hoc per-handler cancel_* sequences (leaked reschedule_expiry/proposal_reminder
# jobs otherwise). ---

@pytest.mark.asyncio
async def test_finish_delete_cancels_all_jobs_and_nothing_else():
    appt_repo = FakeAppointmentRepository([_foreign_appointment()])
    appointment_scheduler = AsyncMock()
    router = _build_router(appt_repo, appointment_scheduler=appointment_scheduler)
    confirm_delete_silent = _find_handler(router, "confirm_delete_silent")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    callback_data = ApptActionCB(
        action="confirm_delete_silent", appointment_id=FOREIGN_APPOINTMENT_ID, mode="list", page=1,
    )

    await confirm_delete_silent(callback_query, callback_data, _state(), _clinic_admin())

    assert appt_repo.deleted == [FOREIGN_APPOINTMENT_ID]
    appointment_scheduler.cancel_all_jobs.assert_awaited_once_with(FOREIGN_APPOINTMENT_ID)
    appointment_scheduler.resync_appointment_jobs.assert_not_called()
    appointment_scheduler.cancel_appointment_reminders.assert_not_called()
    appointment_scheduler.cancel_appointment_completions.assert_not_called()
    appointment_scheduler.cancel_appointment_autocomplete.assert_not_called()
    appointment_scheduler.cancel_auto_confirm.assert_not_called()


@pytest.mark.asyncio
async def test_finish_appointment_resyncs_jobs_and_nothing_else():
    appt_repo = FakeAppointmentRepository([_foreign_appointment()])
    appointment_scheduler = AsyncMock()
    router = _build_router(appt_repo, appointment_scheduler=appointment_scheduler)
    finish_appointment = _find_handler(router, "finish_appointment")

    callback_query = _callback_query(CLINIC_ADMIN_TELEGRAM_ID)
    callback_data = ApptActionCB(
        action="finish_appointment", appointment_id=FOREIGN_APPOINTMENT_ID, mode="list", page=1,
    )

    await finish_appointment(callback_query, callback_data, _state(), _clinic_admin())

    assert appt_repo.status_updates == [(FOREIGN_APPOINTMENT_ID, AppointmentStatus.COMPLETED)]
    appointment_scheduler.resync_appointment_jobs.assert_awaited_once()
    resynced_appointment = appointment_scheduler.resync_appointment_jobs.await_args.args[0]
    assert resynced_appointment.status == AppointmentStatus.COMPLETED

    appointment_scheduler.cancel_all_jobs.assert_not_called()
    appointment_scheduler.cancel_appointment_reminders.assert_not_called()
    appointment_scheduler.cancel_appointment_completions.assert_not_called()
    appointment_scheduler.cancel_appointment_autocomplete.assert_not_called()
    appointment_scheduler.cancel_auto_confirm.assert_not_called()
