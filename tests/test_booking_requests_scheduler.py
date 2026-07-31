"""Scheduler-resync regression tests for booking_requests.py.

docs/booking_requests_resync_refactor_prompt.md: confirm_request,
reject_request and approve_propose_datetime used to call point-in-time
cancel_*/schedule_* methods on the appointment scheduler directly. They now
call the single appointment_scheduler.resync_appointment_jobs(appointment)
instead, matching every other negotiation handler in the project (see
test_reschedule_requests_propose_handler.py:120-156 for the reference
pattern this file follows).

These tests confirm each of the three handlers calls resync_appointment_jobs
exactly once with the (mutated) appointment, and never calls any of the
now-removed manual cancel_*/schedule_* methods.
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


ADMIN_TELEGRAM_ID = 999
ADMIN_ID = 1

LEGACY_SCHEDULER_METHODS = (
    "cancel_pending_expiry",
    "cancel_proposal_reminder",
    "cancel_auto_confirm",
    "schedule_pending_expiry",
    "schedule_proposal_reminder",
    "schedule_appointment_reminders",
    "schedule_appointment_completion",
)


class FakeAppointmentRepository:
    def __init__(self, appointment):
        self.appointment = appointment
        self.status_updates = []
        self.proposed_datetime_updates = []
        self.proposed_by_updates = []
        self.notifications = []
        self.get_notifications_calls = []

    async def get_appointment_by_id(self, appointment_id):
        return self.appointment

    async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None):
        return []

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.status_updates.append((appointment_id, status))

    async def update_proposed_datetime(self, appointment_id, proposed_datetime):
        self.proposed_datetime_updates.append((appointment_id, proposed_datetime))

    async def update_proposed_by(self, appointment_id, proposed_by):
        self.proposed_by_updates.append((appointment_id, proposed_by))

    async def get_appointment_notifications(self, appointment_id, kind):
        self.get_notifications_calls.append((appointment_id, kind))
        return [n for n in self.notifications if n[0] == appointment_id and n[1] == kind]

    async def try_confirm_or_reject_pending(self, appointment_id, new_status, decided_by_user_id, status_updated_at):
        # Deliberately does not mutate self.appointment -- AppointmentManagement
        # applies the equivalent field updates itself afterward, mirroring the
        # real repository which only touches the DB row, never the caller's
        # Python object.
        if self.appointment.status != AppointmentStatus.PENDING or self.appointment.proposed_datetime is not None:
            return False

        self.status_updates.append((appointment_id, new_status))
        return True

    async def try_propose_new_datetime(
        self, appointment_id, proposed_datetime, proposed_by, decided_by_user_id, expected_status
    ):
        if self.appointment.status.value != expected_status:
            return False
        if self.appointment.proposed_datetime is not None and self.appointment.proposed_by == CreatedBy.ADMIN:
            return False

        self.proposed_datetime_updates.append((appointment_id, proposed_datetime))
        self.proposed_by_updates.append((appointment_id, CreatedBy(proposed_by)))
        return True

    async def try_apply_new_datetime_immediately(
        self, appointment_id, new_datetime, decided_by_user_id, status_updated_at, expected_status
    ):
        if self.appointment.status.value != expected_status:
            return False
        if self.appointment.proposed_datetime is not None and self.appointment.proposed_by == CreatedBy.ADMIN:
            return False

        self.status_updates.append((appointment_id, AppointmentStatus.CONFIRMED))
        self.proposed_datetime_updates.append((appointment_id, None))
        self.proposed_by_updates.append((appointment_id, None))
        return True


class FakeUserRepo:
    def __init__(self, client=None):
        self.client = client

    async def get_user_by_telegram_id(self, telegram_user_id):
        return User(
            full_name="Petrov Petr",
            phone="+998907654321",
            role=Role.ADMIN,
            telegram_user_id=ADMIN_TELEGRAM_ID,
            ID=ADMIN_ID,
            clinic_id=1,
            clinic_name="Zub Mudrosti",
        )

    async def get_client_by_id(self, user_id):
        return self.client

    async def get_user_by_id(self, user_id):
        if user_id == ADMIN_ID:
            return await self.get_user_by_telegram_id(ADMIN_TELEGRAM_ID)
        return None


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=1, visibility_scope="clinic")


class FakeClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=1, name="Zub Mudrosti", token="t")


def _pending_booking_request():
    return Appointment(
        clinic_id=1,
        client_id=7,
        doctor_id=5,
        datetime="2026-08-01 10:00",
        purpose="Konsultatsiya",
        created_by=CreatedBy.CLIENT,
        status=AppointmentStatus.PENDING,
        id=1,
    )


def _make_scheduler():
    scheduler = MagicMock()
    scheduler.resync_appointment_jobs = AsyncMock()
    for method_name in LEGACY_SCHEDULER_METHODS:
        setattr(scheduler, method_name, AsyncMock())
    return scheduler


def _assert_only_resync_called(scheduler, appointment):
    scheduler.resync_appointment_jobs.assert_awaited_once_with(appointment)
    for method_name in LEGACY_SCHEDULER_METHODS:
        getattr(scheduler, method_name).assert_not_awaited()


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _build_router(appt_repo, appointment_scheduler, user_repo=None, notification_service=None):
    return create_admin_booking_requests_router(
        appt_repo, user_repo or FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service, appointment_scheduler=appointment_scheduler,
    )


def _make_callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
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
async def test_confirm_request_resyncs_jobs_once_and_skips_legacy_methods():
    appointment = _pending_booking_request()
    appt_repo = FakeAppointmentRepository(appointment)
    appointment_scheduler = _make_scheduler()
    router = _build_router(appt_repo, appointment_scheduler)
    confirm_request = _find_handler(router, "confirm_request")

    await confirm_request(
        _make_callback_query(),
        BookingRequestActionCB(action="confirm", appointment_id=1),
    )

    assert appointment.status is AppointmentStatus.CONFIRMED
    _assert_only_resync_called(appointment_scheduler, appointment)


@pytest.mark.asyncio
async def test_reject_request_resyncs_jobs_once_and_skips_legacy_methods():
    appointment = _pending_booking_request()
    appt_repo = FakeAppointmentRepository(appointment)
    appointment_scheduler = _make_scheduler()
    router = _build_router(appt_repo, appointment_scheduler)
    reject_request = _find_handler(router, "reject_request")

    await reject_request(
        _make_callback_query(),
        BookingRequestActionCB(action="reject", appointment_id=1),
    )

    assert appointment.status is AppointmentStatus.CANCELLED
    _assert_only_resync_called(appointment_scheduler, appointment)


@pytest.mark.asyncio
async def test_approve_propose_datetime_resyncs_jobs_once_and_skips_legacy_methods():
    appointment = _pending_booking_request()
    appt_repo = FakeAppointmentRepository(appointment)
    appointment_scheduler = _make_scheduler()
    router = _build_router(appt_repo, appointment_scheduler)
    approve_propose_datetime = _find_handler(router, "approve_propose_datetime")

    await approve_propose_datetime(
        _make_callback_query(),
        BookingRequestActionCB(action="approve_propose_datetime", appointment_id=1),
        _make_state(),
    )

    assert appointment.status is AppointmentStatus.PENDING
    assert appt_repo.proposed_datetime_updates == [(1, "2026-08-05 12:00")]
    assert appt_repo.proposed_by_updates == [(1, CreatedBy.ADMIN)]
    _assert_only_resync_called(appointment_scheduler, appointment)


@pytest.mark.asyncio
async def test_approve_propose_datetime_immediately_applies_when_client_has_no_telegram_account():
    """A client with no linked Telegram account can never confirm a proposal,
    so the service applies the new time immediately (status -> CONFIRMED,
    proposed_datetime -> None). The handler must then skip the
    notify_client_reschedule_proposed call and the "waiting on client"
    message, while sibling-invalidation and FSM cleanup still run."""
    appointment = _pending_booking_request()
    appt_repo = FakeAppointmentRepository(appointment)
    client = User(
        full_name="Ivanov Ivan", phone="+998901234567", role=Role.CLIENT, ID=7, telegram_user_id=None,
    )
    user_repo = FakeUserRepo(client)
    notification_service = MagicMock()
    notification_service.notify_client_reschedule_proposed = AsyncMock()
    notification_service.invalidate_stale_decision_message = AsyncMock()
    appointment_scheduler = _make_scheduler()
    router = _build_router(appt_repo, appointment_scheduler, user_repo=user_repo, notification_service=notification_service)
    approve_propose_datetime = _find_handler(router, "approve_propose_datetime")
    state = _make_state()
    callback_query = _make_callback_query()

    await approve_propose_datetime(
        callback_query,
        BookingRequestActionCB(action="approve_propose_datetime", appointment_id=1),
        state,
    )

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appointment.proposed_datetime is None
    assert appt_repo.proposed_datetime_updates == [(1, None)]
    assert appt_repo.proposed_by_updates == [(1, None)]
    notification_service.notify_client_reschedule_proposed.assert_not_awaited()

    message_text = callback_query.message.edit_text.await_args.args[0]
    assert "Ожидаем ответа клиента" not in message_text

    assert appt_repo.get_notifications_calls == [(1, "booking")]
    state.clear.assert_awaited_once()
    _assert_only_resync_called(appointment_scheduler, appointment)
