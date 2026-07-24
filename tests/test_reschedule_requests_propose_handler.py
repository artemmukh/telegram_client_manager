"""Handler-level test for reschedule_requests.py's new propose-datetime wizard
(PR2 Part 5): admin can counter-propose a new time on a client's reschedule
request, ending in approve_propose_datetime which calls
AppointmentManagement.propose_new_datetime, resyncs jobs via
AppointmentScheduler.resync_appointment_jobs, notifies the client via
notify_client_appointment_reschedule_proposed, and persists the resulting
message_id via update_proposal_message_id.

Thin, direct-call test in the same style as test_appointment_reschedule_handler.py
and test_appointment_browser_propose_handler.py.
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.admin.appointment_management.reschedule_requests import (
    create_admin_reschedule_requests_router,
)
from bot.keyboards.admin.record_management_kb.reschedule_request_cb import RescheduleRequestActionCB
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


ADMIN_TELEGRAM_ID = 999


class FakeAppointmentRepository:
    def __init__(self, appointment):
        self.appointment = appointment
        self.proposed_datetime_updates = []
        self.proposed_by_updates = []
        self.proposal_message_id_updates = []

    async def get_appointment_by_id(self, appointment_id):
        return self.appointment

    async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None):
        return []

    async def update_proposed_datetime(self, appointment_id, proposed_datetime):
        self.proposed_datetime_updates.append((appointment_id, proposed_datetime))
        self.appointment.proposed_datetime = proposed_datetime

    async def update_proposed_by(self, appointment_id, proposed_by):
        self.proposed_by_updates.append((appointment_id, proposed_by))
        self.appointment.proposed_by = proposed_by

    async def update_proposal_message_id(self, appointment_id, message_id):
        self.proposal_message_id_updates.append((appointment_id, message_id))

    async def try_propose_new_datetime(
        self, appointment_id, proposed_datetime, proposed_by, decided_by_user_id, expected_status
    ):
        # Deliberately does not mutate self.appointment -- AppointmentManagement.
        # propose_new_datetime() applies the equivalent field updates itself
        # afterward, mirroring the real repository which only touches the DB
        # row, never the caller's Python object.
        if self.appointment.status.value != expected_status:
            return False
        if self.appointment.proposed_datetime is not None and self.appointment.proposed_by == CreatedBy.ADMIN:
            return False

        self.proposed_datetime_updates.append((appointment_id, proposed_datetime))
        self.proposed_by_updates.append((appointment_id, CreatedBy(proposed_by)))
        return True


class FakeUserRepo:
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

    async def get_user_by_id(self, user_id):
        # Not needed by the happy-path test in this file; only exercised by the
        # AppointmentAlreadyDecidedError race test below, where the winning
        # colleague resolves to the generic "Другой сотрудник" fallback label.
        return None


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=1, visibility_scope="clinic")


class FakeClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=1, name="Зуб Мудрости", token="t")


def _confirmed_appointment_with_client_proposal():
    return Appointment(
        clinic_id=1,
        client_id=7,
        datetime="2026-08-01 10:00",
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=AppointmentStatus.CONFIRMED,
        id=1,
        proposed_datetime="2026-08-03 09:00",
        proposed_by=CreatedBy.CLIENT,
    )


class RaceFakeAppointmentRepository:
    """CAS-flip fake for the lost-race regression test: staff B's ownership
    check and propose_new_datetime's internal re-read both still show the
    client's outstanding reschedule proposal (proposed_by=CLIENT), but staff A
    has already resolved that very request (e.g. rejected it) by the time B's
    counter-proposal reaches the atomic try_propose_new_datetime call. A single
    shared object can't represent both states, so try_propose_new_datetime
    flips self.current to A's already-committed final row at the moment the
    CAS is (hypothetically) attempted, mirroring the real TOCTOU race against
    the DB. Same pattern as the flip fakes in test_appointment_decision_conflicts.py."""

    def __init__(self, pre_race, post_race):
        self.current = pre_race
        self.post_race = post_race

    async def get_appointment_by_id(self, appointment_id):
        return self.current

    async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None):
        return []

    async def try_propose_new_datetime(
        self, appointment_id, proposed_datetime, proposed_by, decided_by_user_id, expected_status
    ):
        self.current = self.post_race
        return False


def _get_approve_propose_datetime_handler(router):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == "approve_propose_datetime":
            return handler.callback
    raise AssertionError("approve_propose_datetime handler not found on router")


def _make_callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
    callback_query.message.edit_text = AsyncMock()
    callback_query.answer = AsyncMock()
    return callback_query


def _make_state():
    state = MagicMock()
    state.get_data = AsyncMock(return_value={
        "appointment_datetime_parsed": datetime(2026, 8, 5, 12, 0),
        "appointment_datetime_display": "05.08.2026 12:00",
    })
    state.clear = AsyncMock()
    return state


@pytest.mark.asyncio
async def test_approve_propose_datetime_proposes_resyncs_and_notifies():
    """Admin counter-proposes over an outstanding client proposal: the guard
    allows this (proposed_by=CLIENT), propose_new_datetime overwrites it with
    the admin's offer, jobs are resynced, and the client is notified."""
    appointment = _confirmed_appointment_with_client_proposal()
    appt_repo = FakeAppointmentRepository(appointment)

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()
    appointment_scheduler.cancel_reschedule_expiry = AsyncMock()
    appointment_scheduler.schedule_reschedule_expiry = AsyncMock()

    notification_service = MagicMock()
    notification_service.notify_client_appointment_reschedule_proposed = AsyncMock(return_value=654)

    router = create_admin_reschedule_requests_router(
        appt_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service, appointment_scheduler=appointment_scheduler,
    )
    approve_propose_datetime = _get_approve_propose_datetime_handler(router)

    await approve_propose_datetime(
        _make_callback_query(),
        RescheduleRequestActionCB(action="approve_propose_datetime", appointment_id=1),
        _make_state(),
    )

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.proposed_datetime_updates == [(1, "2026-08-05 12:00")]
    assert appt_repo.proposed_by_updates == [(1, CreatedBy.ADMIN)]

    appointment_scheduler.resync_appointment_jobs.assert_awaited_once_with(appointment)
    appointment_scheduler.cancel_reschedule_expiry.assert_not_awaited()
    appointment_scheduler.schedule_reschedule_expiry.assert_not_awaited()

    notification_service.notify_client_appointment_reschedule_proposed.assert_awaited_once_with(appointment)
    assert appt_repo.proposal_message_id_updates == [(1, 654)]


@pytest.mark.asyncio
async def test_approve_propose_datetime_raises_already_decided_with_reschedule_wording():
    """Regression test for the kind threading bug fixed in AppointmentManagement.
    propose_new_datetime: it used to hardcode kind="booking" when raising
    AppointmentAlreadyDecidedError on a lost race, even though this reschedule-
    negotiation call site (reschedule_requests.py's approve_propose_datetime)
    shares the same method. Simulates staff B counter-proposing over a client's
    outstanding reschedule request while staff A has already rejected that same
    request first: the resulting outcome text must say "перенос отклонён"
    (the reschedule-flow wording), never the booking-flow "отклонена" that the
    bug would have silently produced here."""
    pre_race = _confirmed_appointment_with_client_proposal()
    post_race = Appointment(
        clinic_id=1,
        client_id=7,
        datetime="2026-08-01 10:00",
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=AppointmentStatus.CANCELLED,
        id=1,
        proposed_datetime=None,
        proposed_by=None,
        decided_by_user_id=42,
    )
    appt_repo = RaceFakeAppointmentRepository(pre_race, post_race)

    notification_service = MagicMock()
    notification_service.invalidate_stale_decision_message = AsyncMock()

    router = create_admin_reschedule_requests_router(
        appt_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service,
    )
    approve_propose_datetime = _get_approve_propose_datetime_handler(router)

    callback_query = _make_callback_query()
    callback_query.message.chat.id = 555
    callback_query.message.message_id = 777
    state = _make_state()

    await approve_propose_datetime(
        callback_query,
        RescheduleRequestActionCB(action="approve_propose_datetime", appointment_id=1),
        state,
    )

    callback_query.answer.assert_called_once()
    args, kwargs = callback_query.answer.call_args
    assert "уже обработана" in args[0]
    assert kwargs == {"show_alert": True}
    state.clear.assert_awaited_once()

    notification_service.invalidate_stale_decision_message.assert_awaited_once_with(
        555, 777, "Другой сотрудник", "перенос отклонён"
    )
    outcome_text = notification_service.invalidate_stale_decision_message.call_args.args[3]
    assert outcome_text != "отклонена"
