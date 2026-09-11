"""Scheduler contract tests for staff decision reminders.

These tests stay focused on lifecycle and deadline rules; delivery, repository
anchors, and startup recovery are covered separately.
"""

from datetime import datetime, timedelta

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.models.appointment import Appointment
from bot.models.appointment_notification import AppointmentNotification
from bot.services.appointment import appointment_scheduler as scheduler_module
from bot.services.appointment.appointment_scheduler import AppointmentScheduler
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy


@pytest.fixture
def scheduler():
    value = AsyncIOScheduler(timezone="Asia/Tashkent")
    yield value
    try:
        if value.running:
            value.shutdown(wait=False)
    except RuntimeError:
        # pytest-asyncio may close the loop before fixture teardown.
        pass


@pytest.fixture
def appointment_scheduler(scheduler):
    class ReminderManagement:
        async def get_active_notification_targets(self, appointment_id, kind):
            return [
                AppointmentNotification(
                    appointment_id=appointment_id,
                    chat_id=9001,
                    message_id=901,
                    kind=kind,
                    created_at="2026-09-11 12:00:00",
                )
            ]

    return AppointmentScheduler(
        scheduler=scheduler,
        notification_service=object(),
        appointment_management=ReminderManagement(),
    )


def make_appointment(
    now: datetime,
    *,
    status: AppointmentStatus = AppointmentStatus.PENDING,
    created_by: CreatedBy = CreatedBy.CLIENT,
    proposed_datetime: str | None = None,
    proposed_by: CreatedBy | None = None,
    created_at: datetime | None = None,
    target_delta: timedelta = timedelta(days=2),
) -> Appointment:
    target = now + target_delta
    return Appointment(
        id=42,
        clinic_id=1,
        client_id=7,
        datetime=target.isoformat(),
        purpose="consultation",
        created_by=created_by,
        status=status,
        created_at=(created_at or now).isoformat(),
        proposed_datetime=proposed_datetime,
        proposed_by=proposed_by,
    )


def job_ids(scheduler: AsyncIOScheduler) -> set[str]:
    return {job.id for job in scheduler.get_jobs()}


@pytest.mark.asyncio
async def test_plain_client_pending_schedules_booking_decision_reminder(
    appointment_scheduler, scheduler, monkeypatch
):
    now = datetime(2026, 9, 11, 12, 0)
    monkeypatch.setattr(scheduler_module, "_current_tashkent_time", lambda: now)
    appointment = make_appointment(now, created_at=now)
    scheduler.start()

    await appointment_scheduler.resync_appointment_jobs(appointment)

    assert "appt_42_booking_decision_reminder" in job_ids(scheduler)


@pytest.mark.asyncio
async def test_client_pending_reschedule_schedules_reschedule_decision_reminder(
    appointment_scheduler, scheduler, monkeypatch
):
    now = datetime(2026, 9, 11, 12, 0)
    monkeypatch.setattr(scheduler_module, "_current_tashkent_time", lambda: now)
    proposed = (now + timedelta(days=2)).isoformat()
    appointment = make_appointment(
        now,
        proposed_datetime=proposed,
        proposed_by=CreatedBy.CLIENT,
        created_at=now,
    )
    scheduler.start()

    await appointment_scheduler.resync_appointment_jobs(appointment)

    assert "appt_42_reschedule_decision_reminder" in job_ids(scheduler)


@pytest.mark.asyncio
async def test_confirmed_client_reschedule_uses_same_reschedule_reminder_contract(
    appointment_scheduler, scheduler, monkeypatch
):
    now = datetime(2026, 9, 11, 12, 0)
    monkeypatch.setattr(scheduler_module, "_current_tashkent_time", lambda: now)
    proposed = (now + timedelta(days=2)).isoformat()
    appointment = make_appointment(
        now,
        status=AppointmentStatus.CONFIRMED,
        proposed_datetime=proposed,
        proposed_by=CreatedBy.CLIENT,
        created_at=now,
    )
    scheduler.start()

    await appointment_scheduler.resync_appointment_jobs(appointment)

    assert "appt_42_reschedule_decision_reminder" in job_ids(scheduler)


@pytest.mark.asyncio
async def test_admin_originated_proposal_does_not_schedule_staff_decision_reminder(
    appointment_scheduler, scheduler, monkeypatch
):
    now = datetime(2026, 9, 11, 12, 0)
    monkeypatch.setattr(scheduler_module, "_current_tashkent_time", lambda: now)
    proposed = (now + timedelta(days=2)).isoformat()
    appointment = make_appointment(
        now,
        proposed_datetime=proposed,
        proposed_by=CreatedBy.ADMIN,
        created_at=now,
    )
    scheduler.start()

    await appointment_scheduler.resync_appointment_jobs(appointment)

    ids = job_ids(scheduler)
    assert "appt_42_booking_decision_reminder" not in ids
    assert "appt_42_reschedule_decision_reminder" not in ids


@pytest.mark.asyncio
@pytest.mark.parametrize("offset", [timedelta(0), timedelta(hours=-1)])
async def test_reminder_is_not_scheduled_when_first_tick_is_at_or_after_deadline(
    appointment_scheduler, scheduler, monkeypatch, offset
):
    now = datetime(2026, 9, 11, 12, 0)
    monkeypatch.setattr(scheduler_module, "_current_tashkent_time", lambda: now)
    created_at = now - timedelta(hours=12)
    appointment = make_appointment(
        now,
        created_at=created_at,
        target_delta=timedelta(hours=14) + offset,
    )
    scheduler.start()

    await appointment_scheduler.resync_appointment_jobs(appointment)

    assert "appt_42_booking_decision_reminder" not in job_ids(scheduler)


@pytest.mark.asyncio
async def test_transition_from_booking_to_reschedule_cancels_old_reminder(
    appointment_scheduler, scheduler, monkeypatch
):
    now = datetime(2026, 9, 11, 12, 0)
    monkeypatch.setattr(scheduler_module, "_current_tashkent_time", lambda: now)
    booking = make_appointment(now, created_at=now)
    scheduler.start()
    await appointment_scheduler.resync_appointment_jobs(booking)
    assert "appt_42_booking_decision_reminder" in job_ids(scheduler)

    proposed = (now + timedelta(days=2)).isoformat()
    reschedule = make_appointment(
        now,
        proposed_datetime=proposed,
        proposed_by=CreatedBy.CLIENT,
        created_at=now,
    )
    await appointment_scheduler.resync_appointment_jobs(reschedule)

    ids = job_ids(scheduler)
    assert "appt_42_booking_decision_reminder" not in ids
    assert "appt_42_reschedule_decision_reminder" in ids


@pytest.mark.asyncio
async def test_startup_recovery_scans_only_active_decision_cards(
    scheduler, monkeypatch
):
    now = datetime(2026, 9, 11, 12, 0)
    monkeypatch.setattr(scheduler_module, "_current_tashkent_time", lambda: now)
    appointment = make_appointment(now, created_at=now)

    class RecoveryManagement:
        async def get_appointments_with_active_staff_decision_cards(self):
            return [appointment]

        async def get_active_notification_targets(self, appointment_id, kind):
            return [
                AppointmentNotification(
                    appointment_id=appointment_id,
                    chat_id=9001,
                    message_id=901,
                    kind=kind,
                    created_at="2026-09-11 12:00:00",
                )
            ]

    value = AppointmentScheduler(
        scheduler=scheduler,
        notification_service=object(),
        appointment_management=RecoveryManagement(),
    )
    scheduler.start()

    await value.restore_staff_decision_reminder_jobs()

    assert "appt_42_booking_decision_reminder" in job_ids(scheduler)


@pytest.mark.asyncio
async def test_reminder_not_scheduled_when_no_active_anchors(
    scheduler, monkeypatch
):
    now = datetime(2026, 9, 11, 12, 0)
    monkeypatch.setattr(scheduler_module, "_current_tashkent_time", lambda: now)
    appointment = make_appointment(now, created_at=now)

    class EmptyAnchorsManagement:
        async def get_active_notification_targets(self, appointment_id, kind):
            return []

    app_scheduler = AppointmentScheduler(
        scheduler=scheduler,
        notification_service=object(),
        appointment_management=EmptyAnchorsManagement(),
    )
    scheduler.start()

    await app_scheduler.resync_appointment_jobs(appointment)

    assert "appt_42_booking_decision_reminder" not in job_ids(scheduler)


@pytest.mark.asyncio
async def test_resync_cancels_reminder_when_anchors_closed(
    scheduler, monkeypatch
):
    now = datetime(2026, 9, 11, 12, 0)
    monkeypatch.setattr(scheduler_module, "_current_tashkent_time", lambda: now)
    appointment = make_appointment(now, created_at=now)

    class DynamicAnchorsManagement:
        def __init__(self):
            self.has_active = True

        async def get_active_notification_targets(self, appointment_id, kind):
            if self.has_active:
                return [
                    AppointmentNotification(
                        appointment_id=appointment_id,
                        chat_id=9001,
                        message_id=901,
                        kind=kind,
                        created_at="2026-09-11 12:00:00",
                    )
                ]
            return []

    mgmt = DynamicAnchorsManagement()
    app_scheduler = AppointmentScheduler(
        scheduler=scheduler,
        notification_service=object(),
        appointment_management=mgmt,
    )
    scheduler.start()

    await app_scheduler.resync_appointment_jobs(appointment)
    assert "appt_42_booking_decision_reminder" in job_ids(scheduler)

    mgmt.has_active = False
    await app_scheduler.resync_appointment_jobs(appointment)
    assert "appt_42_booking_decision_reminder" not in job_ids(scheduler)


@pytest.mark.asyncio
async def test_startup_recovery_respects_clinic_id(scheduler, monkeypatch):
    now = datetime(2026, 9, 11, 12, 0)
    monkeypatch.setattr(scheduler_module, "_current_tashkent_time", lambda: now)

    called_with = []

    class ScopedRecoveryManagement:
        async def get_appointments_with_active_staff_decision_cards(self, clinic_id=None):
            called_with.append(clinic_id)
            return []

    value = AppointmentScheduler(
        scheduler=scheduler,
        notification_service=object(),
        appointment_management=ScopedRecoveryManagement(),
    )
    scheduler.start()

    await value.restore_staff_decision_reminder_jobs(clinic_id=2)
    assert called_with == [2]

