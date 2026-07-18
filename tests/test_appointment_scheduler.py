"""Tests for AppointmentScheduler service."""

import os
import sqlite3
import tempfile
from pathlib import Path

import aiosqlite
import pytest
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.models.appointment import Appointment
from bot.models.staff import Staff
from bot.models.user import User
from bot.repositories.user_repository import UserRepository
from bot.services.appointment.appointment_jobs import (
    auto_confirm_pending_job,
    expire_pending_request_job,
    expire_reschedule_request_job,
    send_proposal_reminder_job,
)
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_scheduler import (
    AppointmentScheduler,
    _current_tashkent_time,
)
from bot.services.utils.date_parser import get_current_tashkent_time
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role
from scripts.migrate_users_created_at_timezone import migrate_users_created_at


@pytest.fixture
def mock_appointment_repo():
    """Mock AppointmentRepository."""
    repo = AsyncMock()
    return repo


@pytest.fixture
def mock_user_repo():
    """Mock UserRepository."""
    repo = AsyncMock()
    return repo


@pytest.fixture
def mock_staff_repo():
    """Mock StaffRepository. Defaults to no clinic-scope staff (empty list) so
    resolve_notification_recipients falls back to doctor-only unless a test
    explicitly configures get_staff_by_clinic_id."""
    repo = AsyncMock()
    repo.get_staff_by_clinic_id.return_value = []
    return repo


@pytest.fixture
def mock_notification_service():
    """Mock AppointmentNotificationService."""
    service = AsyncMock()
    service.notify_client_reminder_without_buttons = AsyncMock(return_value=True)
    service.notify_client_reminder_with_buttons = AsyncMock(return_value=True)
    service.notify_admin_upcoming_appointment = AsyncMock()
    return service


@pytest.fixture
def mock_appointment_management(mock_appointment_repo, mock_user_repo, mock_staff_repo):
    """Real AppointmentManagement wrapping the mocked repositories, so that
    delegated repo calls remain observable on mock_appointment_repo/mock_user_repo."""
    return AppointmentManagement(
        mock_appointment_repo, mock_user_repo, mock_staff_repo, AsyncMock(),
    )


@pytest.fixture
def scheduler():
    """Create APScheduler instance for testing."""
    sched = AsyncIOScheduler(timezone='Asia/Tashkent')
    yield sched
    # Cleanup - only shutdown if still running
    try:
        if sched.running:
            sched.shutdown(wait=False)
    except Exception:
        # Event loop may already be closed, ignore errors
        pass


@pytest.fixture
def appointment_scheduler(
    scheduler, mock_notification_service, mock_appointment_management
):
    """Create AppointmentScheduler instance."""
    return AppointmentScheduler(
        scheduler=scheduler,
        notification_service=mock_notification_service,
        appointment_management=mock_appointment_management,
    )


@pytest.fixture
def sample_appointment():
    """Create a sample appointment for testing."""
    now = datetime.now()
    appointment_time = now + timedelta(days=2)

    return Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=appointment_time.isoformat(),
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        clinic_name="Test Clinic",
    )


@pytest.mark.asyncio
async def test_schedule_appointment_reminders_creates_two_jobs(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that scheduling creates exactly 2 reminder jobs."""
    scheduler.start()

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 2

    job_ids = {job.id for job in jobs}
    assert f"appt_{sample_appointment.id}_24h" in job_ids
    assert f"appt_{sample_appointment.id}_2h" in job_ids

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_job_ids_follow_correct_pattern(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that job IDs follow the pattern: appt_{id}_{hours}h."""
    scheduler.start()

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    jobs = scheduler.get_jobs()
    for job in jobs:
        assert job.id.startswith(f"appt_{sample_appointment.id}_")
        assert job.id.endswith("h")

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_reminder_times_calculated_correctly(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that reminder times are calculated correctly (24h and 2h before)."""
    scheduler.start()

    appointment_dt = datetime.fromisoformat(sample_appointment.datetime)
    expected_24h_time = appointment_dt - timedelta(hours=24)
    expected_2h_time = appointment_dt - timedelta(hours=2)

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    jobs = scheduler.get_jobs()
    job_times = {job.id: job.next_run_time for job in jobs}

    # Get actual scheduled times
    actual_24h_time = job_times[f"appt_{sample_appointment.id}_24h"]
    actual_2h_time = job_times[f"appt_{sample_appointment.id}_2h"]

    # Replace timezone info to make comparison
    if actual_24h_time.tzinfo:
        expected_24h_time = expected_24h_time.replace(tzinfo=actual_24h_time.tzinfo)
        expected_2h_time = expected_2h_time.replace(tzinfo=actual_2h_time.tzinfo)

    # Check times are close (within 1 second tolerance for datetime precision)
    assert abs(
        (actual_24h_time - expected_24h_time).total_seconds()
    ) < 1
    assert abs(
        (actual_2h_time - expected_2h_time).total_seconds()
    ) < 1

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_appointment_reminders_removes_jobs(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that cancelling reminders removes all scheduled jobs."""
    scheduler.start()

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)
    assert len(scheduler.get_jobs()) == 2

    await appointment_scheduler.cancel_appointment_reminders(sample_appointment.id)
    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_reminders_idempotent_no_error_if_already_cancelled(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that cancelling non-existent reminders doesn't raise error."""
    scheduler.start()

    # Cancel reminders that were never scheduled
    await appointment_scheduler.cancel_appointment_reminders(999)

    # Should not raise error
    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_send_reminder_job_sends_message_if_pending(
    appointment_scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Test that reminder job sends message when appointment is PENDING (24h reminder)."""
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment
    mock_user_repo.get_client_by_id.return_value = MagicMock(full_name="Test Client")
    mock_notification_service.notify_client_reminder_without_buttons = AsyncMock(return_value=True)
    mock_notification_service.notify_admin_upcoming_appointment = AsyncMock()

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        # Setup mocks
        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await appointment_scheduler._send_reminder_job(sample_appointment.id, hours_before=24)

            mock_appointment_repo.get_appointment_by_id.assert_called_once_with(sample_appointment.id)
            mock_notification_service.notify_client_reminder_without_buttons.assert_called_once_with(
                sample_appointment
            )


@pytest.mark.asyncio
async def test_send_reminder_job_sends_message_if_confirmed(
    appointment_scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Test that reminder job sends message when appointment is CONFIRMED (2h reminder with buttons)."""
    confirmed_appointment = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.CONFIRMED,
        clinic_name="Test Clinic",
    )
    mock_appointment_repo.get_appointment_by_id.return_value = confirmed_appointment
    mock_user_repo.get_client_by_id.return_value = MagicMock(full_name="Test Client")
    mock_notification_service.notify_client_reminder_with_buttons = AsyncMock(return_value=True)
    mock_notification_service.notify_admin_upcoming_appointment = AsyncMock()

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await appointment_scheduler._send_reminder_job(confirmed_appointment.id, hours_before=2)

            mock_notification_service.notify_client_reminder_with_buttons.assert_called_once_with(
                confirmed_appointment
            )


@pytest.mark.asyncio
async def test_send_reminder_job_skips_if_cancelled(
    appointment_scheduler, mock_appointment_repo, mock_notification_service, sample_appointment
):
    """Test that reminder job skips sending if appointment is CANCELLED."""
    cancelled_appointment = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.CANCELLED,
        clinic_name="Test Clinic",
    )
    mock_appointment_repo.get_appointment_by_id.return_value = cancelled_appointment

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_notif_class.return_value = mock_notification_service

            await appointment_scheduler._send_reminder_job(cancelled_appointment.id)

            mock_notification_service.notify_client_reminder_without_buttons.assert_not_called()
            mock_notification_service.notify_client_reminder_with_buttons.assert_not_called()


@pytest.mark.asyncio
async def test_send_reminder_job_skips_if_completed(
    appointment_scheduler, mock_appointment_repo, mock_notification_service, sample_appointment
):
    """Test that reminder job skips sending if appointment is COMPLETED."""
    completed_appointment = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.COMPLETED,
        clinic_name="Test Clinic",
    )
    mock_appointment_repo.get_appointment_by_id.return_value = completed_appointment

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_notif_class.return_value = mock_notification_service

            await appointment_scheduler._send_reminder_job(completed_appointment.id)

            mock_notification_service.notify_client_reminder_without_buttons.assert_not_called()
            mock_notification_service.notify_client_reminder_with_buttons.assert_not_called()


@pytest.mark.asyncio
async def test_send_reminder_job_skips_if_no_show(
    appointment_scheduler, mock_appointment_repo, mock_notification_service, sample_appointment
):
    """Test that reminder job skips sending if appointment is NO_SHOW."""
    no_show_appointment = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.NO_SHOW,
        clinic_name="Test Clinic",
    )
    mock_appointment_repo.get_appointment_by_id.return_value = no_show_appointment

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_notif_class.return_value = mock_notification_service

            await appointment_scheduler._send_reminder_job(no_show_appointment.id)

            mock_notification_service.notify_client_reminder_without_buttons.assert_not_called()
            mock_notification_service.notify_client_reminder_with_buttons.assert_not_called()


@pytest.mark.asyncio
async def test_send_reminder_job_handles_missing_appointment(
    appointment_scheduler, mock_appointment_repo, mock_notification_service
):
    """Test that reminder job handles case where appointment is not found."""
    mock_appointment_repo.get_appointment_by_id.return_value = None

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_notif_class.return_value = mock_notification_service

            # Should not raise error
            await appointment_scheduler._send_reminder_job(999)

            mock_notification_service.notify_client_reminder_without_buttons.assert_not_called()
            mock_notification_service.notify_client_reminder_with_buttons.assert_not_called()


@pytest.mark.asyncio
async def test_send_reminder_job_handles_notification_failure(
    appointment_scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Test that reminder job handles client notification failure gracefully AND sends admin notification."""
    # Setup appointment with a treating doctor
    sample_appointment.doctor_id = 42
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment
    mock_user_repo.get_client_by_id.return_value = MagicMock(full_name="Test Client")
    mock_user_repo.get_user_by_id.return_value = User(
        ID=42, full_name="Test Doctor", phone="+998907654321", role=Role.ADMIN,
        telegram_user_id=12345, reminder_24h=True, reminder_2h=True,
    )

    # Client notification fails (exception)
    mock_notification_service.notify_client_reminder_without_buttons = AsyncMock(
        side_effect=Exception("Network error")
    )
    # But admin notification should still be attempted
    mock_notification_service.notify_admin_upcoming_appointment = AsyncMock()

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            # Should not raise error even if client notification fails
            await appointment_scheduler._send_reminder_job(sample_appointment.id, hours_before=24)

            # Verify client notification was attempted
            mock_notification_service.notify_client_reminder_without_buttons.assert_called_once()
            # Verify admin notification was still attempted despite client failure
            mock_notification_service.notify_admin_upcoming_appointment.assert_called_once()


@pytest.mark.asyncio
async def test_reschedule_reminders_when_datetime_changes(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that reminders can be rescheduled when appointment datetime changes."""
    scheduler.start()

    # Schedule initial reminders
    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)
    initial_jobs = scheduler.get_jobs()
    assert len(initial_jobs) == 2

    # Update appointment with new datetime
    new_datetime = datetime.fromisoformat(sample_appointment.datetime) + timedelta(hours=5)
    sample_appointment.datetime = new_datetime.isoformat()

    # Cancel old and schedule new reminders
    await appointment_scheduler.cancel_appointment_reminders(sample_appointment.id)
    assert len(scheduler.get_jobs()) == 0

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)
    new_jobs = scheduler.get_jobs()
    assert len(new_jobs) == 2

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_appointment_without_id_not_scheduled(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that appointments without ID are not scheduled."""
    scheduler.start()

    sample_appointment.id = None
    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_due_reminders_not_scheduled_when_appointment_too_soon(
    appointment_scheduler, scheduler, sample_appointment
):
    """Both the 24h and 2h reminder times are already in the past when the
    appointment itself is only 1 hour away, so no jobs should be scheduled."""
    scheduler.start()

    sample_appointment.datetime = (_current_tashkent_time() + timedelta(hours=1)).isoformat()

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_due_24h_reminder_skipped_but_2h_reminder_still_scheduled(
    appointment_scheduler, scheduler, sample_appointment
):
    """When the appointment is 3 hours away, the 24h reminder time has already
    passed and must be skipped, while the 2h reminder is still in the future
    and must be scheduled."""
    scheduler.start()

    sample_appointment.datetime = (_current_tashkent_time() + timedelta(hours=3)).isoformat()

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    jobs = scheduler.get_jobs()
    job_ids = {job.id for job in jobs}
    assert job_ids == {f"appt_{sample_appointment.id}_2h"}

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_due_reminder_scheduling_does_not_call_add_job(
    appointment_scheduler, scheduler, sample_appointment
):
    """Regression test for the past-due guard: add_job must not be invoked at
    all when every computed reminder time is already in the past."""
    scheduler.start()

    sample_appointment.datetime = (_current_tashkent_time() + timedelta(minutes=30)).isoformat()

    with patch.object(scheduler, "add_job") as mock_add_job:
        await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

        mock_add_job.assert_not_called()

    scheduler.shutdown(wait=False)


# Reminder scheduling is unconditional (Phase 3b + Fix 3 admin preferences)
#
# schedule_appointment_reminders() no longer reads reminder preferences at
# all - it always schedules both the 24h and 2h job, subject only to the
# past-due guard. Client/admin reminder_24h/reminder_2h are read live by
# send_reminder_job() when a job actually fires (see the firing tests
# further down), not by the scheduler. Each test below still arranges the
# same preference combo that used to gate scheduling (via mock_user_repo);
# the scheduler never reads it, and the assertion proves scheduling now
# ignores it and always schedules both jobs anyway.


def _client_with_preferences(reminder_24h: bool, reminder_2h: bool) -> User:
    return User(
        ID=1,
        full_name="Test Client",
        phone="+998901234567",
        role=Role.CLIENT,
        reminder_24h=reminder_24h,
        reminder_2h=reminder_2h,
    )


def _admin_with_preferences(reminder_24h: bool, reminder_2h: bool) -> User:
    return User(
        ID=99,
        full_name="Test Admin",
        phone="+998907654321",
        role=Role.ADMIN,
        reminder_24h=reminder_24h,
        reminder_2h=reminder_2h,
    )


@pytest.mark.asyncio
async def test_reminders_respect_both_enabled_preference(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """Client with both reminders enabled gets both jobs scheduled (admin
    pinned opted-out so this isolates the client's own preference)."""
    scheduler.start()
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(True, True)
    mock_user_repo.get_user_by_telegram_id.return_value = _admin_with_preferences(False, False)

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        f"appt_{sample_appointment.id}_24h",
        f"appt_{sample_appointment.id}_2h",
    }

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_both_jobs_scheduled_when_client_wants_only_24h(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """This combo used to suppress the 2h job. Scheduling no longer consults
    preferences at all, so a client who opted out of the 2h reminder (and an
    admin who wants nothing) still gets both the 24h and 2h job scheduled;
    the preference is only enforced live when a job fires."""
    scheduler.start()
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(True, False)
    mock_user_repo.get_user_by_telegram_id.return_value = _admin_with_preferences(False, False)

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        f"appt_{sample_appointment.id}_24h",
        f"appt_{sample_appointment.id}_2h",
    }

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_both_jobs_scheduled_when_client_wants_only_2h(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """Mirror case: this combo used to suppress the 24h job. A client who
    opted out of the 24h reminder (and an admin who wants nothing) still
    gets both the 24h and 2h job scheduled; the preference is only enforced
    live when a job fires."""
    scheduler.start()
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(False, True)
    mock_user_repo.get_user_by_telegram_id.return_value = _admin_with_preferences(False, False)

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        f"appt_{sample_appointment.id}_24h",
        f"appt_{sample_appointment.id}_2h",
    }

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_both_jobs_scheduled_when_all_preferences_disabled(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """This combo used to schedule nothing at all. A client and admin who
    both opted out of everything still get both reminder jobs scheduled;
    disabled preferences only suppress the actual send at firing time, never
    the scheduling itself."""
    scheduler.start()
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(False, False)
    mock_user_repo.get_user_by_telegram_id.return_value = _admin_with_preferences(False, False)

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        f"appt_{sample_appointment.id}_24h",
        f"appt_{sample_appointment.id}_2h",
    }

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_reminders_default_to_both_when_client_not_found(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """When the client can't be resolved, fall back to wanting both reminders.
    Admin is pinned opted-out so the result is fully explained by the client's
    own default, not by an unrelated admin preference."""
    scheduler.start()
    mock_user_repo.get_client_by_id.return_value = None
    mock_user_repo.get_user_by_telegram_id.return_value = _admin_with_preferences(False, False)

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        f"appt_{sample_appointment.id}_24h",
        f"appt_{sample_appointment.id}_2h",
    }

    scheduler.shutdown(wait=False)


# Fix 3: admin reminder preferences - scheduling half
#
# schedule_appointment_reminders() always schedules both slots now,
# regardless of client/admin preference; it no longer computes or threads
# real per-party flags into the job's args, nor does it read mock_user_repo
# at all. The (True, True) args below are inert placeholders kept only for
# backward compatibility with the send_reminder_job signature - the firing
# job re-reads live preferences instead (see the firing tests further down).


@pytest.mark.asyncio
async def test_admin_only_wanting_24h_slot_still_schedules_job(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """Client opted out of the 24h reminder, admin wants it: the 24h job is
    scheduled unconditionally regardless of who wants the slot, and carries
    the inert (True, True) placeholder args."""
    scheduler.start()
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(False, True)
    mock_user_repo.get_user_by_telegram_id.return_value = _admin_with_preferences(True, True)

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {
        f"appt_{sample_appointment.id}_24h",
        f"appt_{sample_appointment.id}_2h",
    }
    assert jobs[f"appt_{sample_appointment.id}_24h"].args == (
        sample_appointment.id, 24, True, True,
    )

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_admin_only_wanting_2h_slot_still_schedules_job(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """Admin opted out of the 2h reminder, client wants it: the 2h job is
    scheduled unconditionally regardless of who wants the slot, and carries
    the inert (True, True) placeholder args."""
    scheduler.start()
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(True, True)
    mock_user_repo.get_user_by_telegram_id.return_value = _admin_with_preferences(True, False)

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {
        f"appt_{sample_appointment.id}_24h",
        f"appt_{sample_appointment.id}_2h",
    }
    assert jobs[f"appt_{sample_appointment.id}_2h"].args == (
        sample_appointment.id, 2, True, True,
    )

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_add_job_called_for_both_slots_even_when_neither_wants_2h(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """Neither client nor admin wants the 2h slot, yet add_job is still
    invoked for both it and the 24h slot (stronger guarantee than just
    "present in the final job list") - scheduling is unconditional."""
    scheduler.start()
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(True, False)
    mock_user_repo.get_user_by_telegram_id.return_value = _admin_with_preferences(True, False)

    with patch.object(scheduler, "add_job") as mock_add_job:
        await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    scheduled_ids = {call.kwargs.get("id") for call in mock_add_job.call_args_list}
    assert scheduled_ids == {
        f"appt_{sample_appointment.id}_24h",
        f"appt_{sample_appointment.id}_2h",
    }

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_admin_unresolved_defaults_to_wanting_slot(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """Scheduling doesn't resolve the admin at all anymore, so both jobs are
    scheduled with the inert (True, True) placeholder args regardless of
    whether get_user_by_telegram_id would resolve to anything."""
    scheduler.start()
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(False, False)
    mock_user_repo.get_user_by_telegram_id.return_value = None

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {
        f"appt_{sample_appointment.id}_24h",
        f"appt_{sample_appointment.id}_2h",
    }
    assert jobs[f"appt_{sample_appointment.id}_24h"].args == (
        sample_appointment.id, 24, True, True,
    )
    assert jobs[f"appt_{sample_appointment.id}_2h"].args == (
        sample_appointment.id, 2, True, True,
    )

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_due_slot_skipped_even_when_both_client_and_admin_want_it(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """The past-due guard is not bypassed by wanting: with the appointment only
    3 hours away, the 24h reminder time has already passed and must be skipped
    even though both client and admin want every slot."""
    scheduler.start()
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(True, True)
    mock_user_repo.get_user_by_telegram_id.return_value = _admin_with_preferences(True, True)

    sample_appointment.datetime = (_current_tashkent_time() + timedelta(hours=3)).isoformat()

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {f"appt_{sample_appointment.id}_2h"}

    scheduler.shutdown(wait=False)


# Fix 3 + zombie-preference fix: job firing half
#
# send_reminder_job() no longer trusts the notify_client/notify_admin
# arguments it's called with (they're inert placeholders, see the scheduling
# tests above) - it reads each party's reminder_24h/reminder_2h fresh from
# the database via get_client_by_id/get_user_by_telegram_id at firing time
# and gates each party's send independently on that live value. The
# notify_client/notify_admin kwargs passed below are deliberately the
# opposite of the mocked live preference, so a pass here proves the live DB
# read - not the frozen argument - decides the outcome.


@pytest.mark.asyncio
async def test_fired_reminder_suppresses_client_when_only_admin_wants_24h_slot(
    appointment_scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Client reminder_24h=False, admin reminder_24h=True (read live from the
    DB at firing time): the CLIENT message must NOT be sent while the ADMIN
    message IS sent. The job is fired with the opposite notify_client/
    notify_admin kwargs to prove those frozen args no longer decide anything."""
    sample_appointment.doctor_id = 42
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(False, True)
    admin = _admin_with_preferences(True, True)
    admin.telegram_user_id = 12345
    mock_user_repo.get_user_by_id.return_value = admin

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await appointment_scheduler._send_reminder_job(
                sample_appointment.id, hours_before=24, notify_client=True, notify_admin=False,
            )

            mock_notification_service.notify_client_reminder_without_buttons.assert_not_called()
            mock_notification_service.notify_client_reminder_with_buttons.assert_not_called()
            mock_notification_service.notify_admin_upcoming_appointment.assert_called_once_with(
                12345, sample_appointment, "Test Client",
            )


@pytest.mark.asyncio
async def test_fired_reminder_suppresses_admin_when_only_client_wants_2h_slot(
    appointment_scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Mirror case: two resolved recipients (the treating doctor + a clinic-scope
    admin), each with their OWN reminder_2h read live from the DB at firing time.
    The doctor opted out (reminder_2h=False) and must NOT get a message; the
    clinic-scope admin opted in (reminder_2h=True) and must. The appointment
    deliberately has no doctor_id/clinic-scope staff resolved via the frozen
    notify_client/notify_admin kwargs -- those are fired as the opposite of the
    live preferences to prove the live DB read, not the frozen args, decides the
    outcome. (Regression note: an earlier version of this test resolved zero
    recipients at all -- doctor_id unset, no clinic-scope staff -- so the admin
    loop body never ran and the assertion passed vacuously without exercising any
    gating logic. This version resolves two real, independently-gated recipients.)"""
    sample_appointment.doctor_id = 42
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(True, True)

    doctor = _admin_with_preferences(True, False)
    doctor.telegram_user_id = 54321
    clinic_admin = _admin_with_preferences(True, True)
    clinic_admin.telegram_user_id = 99999

    mock_user_repo.get_user_by_id.side_effect = lambda user_id: doctor if user_id == 42 else None
    mock_user_repo.get_user_by_telegram_id.side_effect = (
        lambda telegram_id: clinic_admin if telegram_id == 99999 else None
    )

    mock_staff_repo = AsyncMock()
    mock_staff_repo.get_staff_by_clinic_id.return_value = [
        Staff(telegram_user_id=99999, clinic_id=sample_appointment.clinic_id, visibility_scope="clinic"),
    ]

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.StaffRepository") as mock_staff_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_staff_repo_class.return_value = mock_staff_repo
            mock_notif_class.return_value = mock_notification_service

            await appointment_scheduler._send_reminder_job(
                sample_appointment.id, hours_before=2, notify_client=False, notify_admin=True,
            )

            mock_notification_service.notify_client_reminder_with_buttons.assert_called_once_with(
                sample_appointment
            )
            mock_notification_service.notify_admin_upcoming_appointment.assert_called_once_with(
                99999, sample_appointment, "Test Client",
            )


@pytest.mark.asyncio
async def test_fired_reminder_gates_multiple_clinic_admins_independently(
    appointment_scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Two clinic-scope admins (no treating doctor involved at all) each have
    their own reminder_24h preference: only the one who wants it gets sent to,
    the other is skipped, proving per-recipient gating scales beyond a single
    doctor/admin pair."""
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(True, True)

    wants_admin = _admin_with_preferences(True, True)
    wants_admin.telegram_user_id = 11111
    opts_out_admin = _admin_with_preferences(False, True)
    opts_out_admin.telegram_user_id = 22222

    mock_user_repo.get_user_by_telegram_id.side_effect = {
        11111: wants_admin,
        22222: opts_out_admin,
    }.get

    mock_staff_repo = AsyncMock()
    mock_staff_repo.get_staff_by_clinic_id.return_value = [
        Staff(telegram_user_id=11111, clinic_id=sample_appointment.clinic_id, visibility_scope="clinic"),
        Staff(telegram_user_id=22222, clinic_id=sample_appointment.clinic_id, visibility_scope="clinic"),
    ]

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.StaffRepository") as mock_staff_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_staff_repo_class.return_value = mock_staff_repo
            mock_notif_class.return_value = mock_notification_service

            await appointment_scheduler._send_reminder_job(sample_appointment.id, hours_before=24)

            mock_notification_service.notify_admin_upcoming_appointment.assert_called_once_with(
                11111, sample_appointment, "Test Client",
            )


@pytest.mark.asyncio
async def test_fired_reminder_sends_to_both_when_both_want_slot(
    appointment_scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Both client and admin want a slot (read live from the DB at firing
    time) -> both messages sent (existing behavior, must not regress). The
    job is fired with notify_client=False, notify_admin=False to prove the
    live DB read - not the frozen args - decides the outcome."""
    sample_appointment.doctor_id = 42
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(True, True)
    admin = _admin_with_preferences(True, True)
    admin.telegram_user_id = 12345
    mock_user_repo.get_user_by_id.return_value = admin

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await appointment_scheduler._send_reminder_job(
                sample_appointment.id, hours_before=2, notify_client=False, notify_admin=False,
            )

            mock_notification_service.notify_client_reminder_with_buttons.assert_called_once_with(
                sample_appointment
            )
            mock_notification_service.notify_admin_upcoming_appointment.assert_called_once_with(
                12345, sample_appointment, "Test Client",
            )


# Phase 4: Auto-Complete Tests


@pytest.mark.asyncio
async def test_schedule_appointment_completion_creates_job(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that scheduling completion creates exactly 1 job."""
    scheduler.start()

    await appointment_scheduler.schedule_appointment_completion(sample_appointment)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == f"appt_{sample_appointment.id}_complete"

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_completion_job_id_correct(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that completion job ID follows pattern: appt_{id}_complete."""
    scheduler.start()

    await appointment_scheduler.schedule_appointment_completion(sample_appointment)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == f"appt_{sample_appointment.id}_complete"

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_completion_time_calculated_correctly(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that completion time is calculated correctly (1h after appointment)."""
    scheduler.start()

    appointment_dt = datetime.fromisoformat(sample_appointment.datetime)
    expected_completion_time = appointment_dt + timedelta(hours=1)

    await appointment_scheduler.schedule_appointment_completion(sample_appointment)

    jobs = scheduler.get_jobs()
    actual_completion_time = jobs[0].next_run_time

    # Replace timezone info to make comparison
    if actual_completion_time.tzinfo:
        expected_completion_time = expected_completion_time.replace(tzinfo=actual_completion_time.tzinfo)

    # Check times are close (within 1 second tolerance for datetime precision)
    assert abs(
        (actual_completion_time - expected_completion_time).total_seconds()
    ) < 1

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_appointment_completions_removes_job(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that cancelling completion removes the scheduled job."""
    scheduler.start()

    await appointment_scheduler.schedule_appointment_completion(sample_appointment)
    assert len(scheduler.get_jobs()) == 1

    await appointment_scheduler.cancel_appointment_completions(sample_appointment.id)
    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_completions_idempotent_no_error(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that cancelling non-existent completion doesn't raise error."""
    scheduler.start()

    # Cancel completion that was never scheduled
    await appointment_scheduler.cancel_appointment_completions(999)

    # Should not raise error
    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_mark_appointment_completed_job_sends_prompt_and_keeps_status_if_pending(
    appointment_scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Test that completion job sends the admin follow-up prompt without changing status if PENDING."""
    sample_appointment.doctor_id = 42
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment
    mock_user_repo.get_user_by_id.return_value = User(
        ID=42, full_name="Test Doctor", phone="+998907654321", role=Role.ADMIN, telegram_user_id=54321,
    )

    await appointment_scheduler._mark_appointment_completed_job(sample_appointment.id)

    mock_appointment_repo.update_appointment_status.assert_not_called()
    mock_notification_service.notify_admin_completion.assert_called_once_with(
        54321, sample_appointment,
    )


@pytest.mark.asyncio
async def test_mark_appointment_completed_job_sends_prompt_and_keeps_status_if_confirmed(
    appointment_scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Test that completion job sends the admin follow-up prompt without changing status if CONFIRMED."""
    confirmed_appointment = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.CONFIRMED,
        clinic_name="Test Clinic",
        doctor_id=42,
    )
    mock_appointment_repo.get_appointment_by_id.return_value = confirmed_appointment
    mock_user_repo.get_user_by_id.return_value = User(
        ID=42, full_name="Test Doctor", phone="+998907654321", role=Role.ADMIN, telegram_user_id=54321,
    )

    await appointment_scheduler._mark_appointment_completed_job(confirmed_appointment.id)

    mock_appointment_repo.update_appointment_status.assert_not_called()
    mock_notification_service.notify_admin_completion.assert_called_once_with(
        54321, confirmed_appointment,
    )


@pytest.mark.asyncio
async def test_mark_appointment_completed_job_skips_if_cancelled(
    appointment_scheduler, mock_appointment_repo, sample_appointment
):
    """Test that completion job skips if appointment is already CANCELLED."""
    cancelled_appointment = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.CANCELLED,
        clinic_name="Test Clinic",
    )
    mock_appointment_repo.get_appointment_by_id.return_value = cancelled_appointment

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class:
            mock_repo_class.return_value = mock_appointment_repo

            await appointment_scheduler._mark_appointment_completed_job(cancelled_appointment.id)

            mock_appointment_repo.update_appointment_status.assert_not_called()


@pytest.mark.asyncio
async def test_mark_appointment_completed_job_skips_if_no_show(
    appointment_scheduler, mock_appointment_repo, sample_appointment
):
    """Test that completion job skips if appointment is already NO_SHOW."""
    no_show_appointment = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.NO_SHOW,
        clinic_name="Test Clinic",
    )
    mock_appointment_repo.get_appointment_by_id.return_value = no_show_appointment

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class:
            mock_repo_class.return_value = mock_appointment_repo

            await appointment_scheduler._mark_appointment_completed_job(no_show_appointment.id)

            mock_appointment_repo.update_appointment_status.assert_not_called()


@pytest.mark.asyncio
async def test_mark_appointment_completed_job_skips_if_already_completed(
    appointment_scheduler, mock_appointment_repo, sample_appointment
):
    """Test that completion job skips if appointment is already COMPLETED."""
    completed_appointment = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.COMPLETED,
        clinic_name="Test Clinic",
    )
    mock_appointment_repo.get_appointment_by_id.return_value = completed_appointment

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class:
            mock_repo_class.return_value = mock_appointment_repo

            await appointment_scheduler._mark_appointment_completed_job(completed_appointment.id)

            mock_appointment_repo.update_appointment_status.assert_not_called()


@pytest.mark.asyncio
async def test_mark_appointment_completed_job_handles_missing_appointment(
    appointment_scheduler, mock_appointment_repo
):
    """Test that completion job handles case where appointment is not found."""
    mock_appointment_repo.get_appointment_by_id.return_value = None

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class:
            mock_repo_class.return_value = mock_appointment_repo

            # Should not raise error
            await appointment_scheduler._mark_appointment_completed_job(999)

            mock_appointment_repo.update_appointment_status.assert_not_called()


@pytest.mark.asyncio
async def test_reschedule_completion_when_datetime_changes(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that completion can be rescheduled when appointment datetime changes."""
    scheduler.start()

    # Schedule initial completion
    await appointment_scheduler.schedule_appointment_completion(sample_appointment)
    initial_jobs = scheduler.get_jobs()
    assert len(initial_jobs) == 1
    initial_time = initial_jobs[0].next_run_time

    # Update appointment with new datetime
    new_datetime = datetime.fromisoformat(sample_appointment.datetime) + timedelta(hours=5)
    sample_appointment.datetime = new_datetime.isoformat()

    # Cancel old and schedule new completion
    await appointment_scheduler.cancel_appointment_completions(sample_appointment.id)
    assert len(scheduler.get_jobs()) == 0

    await appointment_scheduler.schedule_appointment_completion(sample_appointment)
    new_jobs = scheduler.get_jobs()
    assert len(new_jobs) == 1
    new_time = new_jobs[0].next_run_time

    # New time should be 5 hours later
    time_difference = (new_time - initial_time).total_seconds() / 3600
    assert abs(time_difference - 5) < 0.1

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_appointment_without_id_completion_not_scheduled(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that appointments without ID are not scheduled for completion."""
    scheduler.start()

    sample_appointment.id = None
    await appointment_scheduler.schedule_appointment_completion(sample_appointment)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_due_completion_not_scheduled(
    appointment_scheduler, scheduler, sample_appointment
):
    """When appointment datetime + 1h completion time is already in the past
    (e.g. a very old appointment), no completion job should be scheduled."""
    scheduler.start()

    sample_appointment.datetime = (_current_tashkent_time() - timedelta(hours=5)).isoformat()

    await appointment_scheduler.schedule_appointment_completion(sample_appointment)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_due_completion_scheduling_does_not_call_add_job(
    appointment_scheduler, scheduler, sample_appointment
):
    """Regression test for the past-due guard: add_job must not be invoked
    when the computed completion time is already in the past."""
    scheduler.start()

    sample_appointment.datetime = (_current_tashkent_time() - timedelta(minutes=90)).isoformat()

    with patch.object(scheduler, "add_job") as mock_add_job:
        await appointment_scheduler.schedule_appointment_completion(sample_appointment)

        mock_add_job.assert_not_called()

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_multiple_appointments_independent_completions(
    appointment_scheduler, scheduler
):
    """Test that multiple appointments have independent completion jobs."""
    scheduler.start()

    # Create and schedule two appointments
    appt1 = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=(datetime.now() + timedelta(days=1)).isoformat(),
        purpose="Service 1",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        clinic_name="Clinic",
    )
    appt2 = Appointment(
        id=2,
        clinic_id=1,
        client_id=2,
        datetime=(datetime.now() + timedelta(days=2)).isoformat(),
        purpose="Service 2",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        clinic_name="Clinic",
    )

    await appointment_scheduler.schedule_appointment_completion(appt1)
    await appointment_scheduler.schedule_appointment_completion(appt2)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 2

    job_ids = {job.id for job in jobs}
    assert "appt_1_complete" in job_ids
    assert "appt_2_complete" in job_ids

    # Cancel one completion should not affect the other
    await appointment_scheduler.cancel_appointment_completions(1)
    remaining_jobs = scheduler.get_jobs()
    assert len(remaining_jobs) == 1
    assert remaining_jobs[0].id == "appt_2_complete"

    scheduler.shutdown(wait=False)


# Phase 2a: Client Self-Booking Pending Expiry Tests


@pytest.mark.asyncio
async def test_schedule_pending_expiry_creates_job(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that scheduling pending expiry creates exactly 1 job."""
    scheduler.start()

    await appointment_scheduler.schedule_pending_expiry(sample_appointment)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == f"appt_{sample_appointment.id}_expire"

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_pending_expiry_job_id_correct(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that pending expiry job ID follows pattern: appt_{id}_expire."""
    scheduler.start()

    await appointment_scheduler.schedule_pending_expiry(sample_appointment)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == f"appt_{sample_appointment.id}_expire"

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_pending_expiry_time_calculated_correctly(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that pending expiry runs 2 hours before the appointment's requested datetime."""
    scheduler.start()

    expected_expiry_time = datetime.fromisoformat(sample_appointment.datetime) - timedelta(hours=2)

    await appointment_scheduler.schedule_pending_expiry(sample_appointment)

    jobs = scheduler.get_jobs()
    actual_expiry_time = jobs[0].next_run_time

    if actual_expiry_time.tzinfo:
        expected_expiry_time = expected_expiry_time.replace(tzinfo=actual_expiry_time.tzinfo)

    assert abs(
        (actual_expiry_time - expected_expiry_time).total_seconds()
    ) < 1

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_pending_expiry_removes_job(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that cancelling pending expiry removes the scheduled job."""
    scheduler.start()

    await appointment_scheduler.schedule_pending_expiry(sample_appointment)
    assert len(scheduler.get_jobs()) == 1

    await appointment_scheduler.cancel_pending_expiry(sample_appointment.id)
    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_pending_expiry_idempotent_no_error(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that cancelling non-existent pending expiry doesn't raise error."""
    scheduler.start()

    # Cancel pending expiry that was never scheduled
    await appointment_scheduler.cancel_pending_expiry(999)

    # Should not raise error
    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_appointment_without_id_pending_expiry_not_scheduled(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that appointments without ID are not scheduled for pending expiry."""
    scheduler.start()

    sample_appointment.id = None
    await appointment_scheduler.schedule_pending_expiry(sample_appointment)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_due_pending_expiry_not_scheduled(
    appointment_scheduler, scheduler, sample_appointment
):
    """When the appointment's requested datetime is already in the past, no
    pending expiry job should be scheduled."""
    scheduler.start()

    sample_appointment.datetime = (_current_tashkent_time() - timedelta(hours=1)).isoformat()

    await appointment_scheduler.schedule_pending_expiry(sample_appointment)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_due_pending_expiry_scheduling_does_not_call_add_job(
    appointment_scheduler, scheduler, sample_appointment
):
    """Regression test for the past-due guard: add_job must not be invoked
    when the appointment's requested datetime is already in the past."""
    scheduler.start()

    sample_appointment.datetime = (_current_tashkent_time() - timedelta(minutes=30)).isoformat()

    with patch.object(scheduler, "add_job") as mock_add_job:
        await appointment_scheduler.schedule_pending_expiry(sample_appointment)

        mock_add_job.assert_not_called()

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_pending_expiry_rescheduled_without_duplicate_job_on_direct_client_edit(
    appointment_scheduler, scheduler, sample_appointment
):
    """When a client edits the datetime of their own PENDING self-booking request
    directly (same row), the handler re-arms pending expiry via
    cancel_pending_expiry + schedule_pending_expiry against the updated appointment.
    This must replace the old job, not leave a duplicate behind, and the new job's
    run time must reflect the new datetime."""
    scheduler.start()

    await appointment_scheduler.schedule_pending_expiry(sample_appointment)
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    job_id = f"appt_{sample_appointment.id}_expire"
    assert jobs[0].id == job_id
    old_run_time = jobs[0].next_run_time

    new_datetime = datetime.fromisoformat(sample_appointment.datetime) + timedelta(days=1)
    sample_appointment.datetime = new_datetime.isoformat()

    await appointment_scheduler.cancel_pending_expiry(sample_appointment.id)
    await appointment_scheduler.schedule_pending_expiry(sample_appointment)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == job_id

    expected_run_time = new_datetime - timedelta(hours=2)
    actual_run_time = jobs[0].next_run_time
    if actual_run_time.tzinfo:
        expected_run_time = expected_run_time.replace(tzinfo=actual_run_time.tzinfo)
    assert abs((actual_run_time - expected_run_time).total_seconds()) < 1
    assert actual_run_time != old_run_time

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_expire_pending_request_job_expires_if_pending_and_client_created(
    mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Test that the expiry job cancels a still-PENDING, client-created self-booking request."""
    client_request = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=AppointmentStatus.PENDING,
        clinic_name="Test Clinic",
    )
    mock_appointment_repo.get_appointment_by_id.return_value = client_request
    mock_notification_service.notify_client_pending_request_expired = AsyncMock(return_value=True)

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await expire_pending_request_job(client_request.id)

            mock_appointment_repo.update_appointment_status.assert_called_once_with(
                client_request.id,
                AppointmentStatus.EXPIRED,
                ANY,
            )
            mock_notification_service.notify_client_pending_request_expired.assert_called_once_with(
                client_request
            )


@pytest.mark.asyncio
async def test_expire_pending_request_job_skips_if_not_pending(
    mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Test that the expiry job skips a client-created request that is no longer PENDING."""
    confirmed_request = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=AppointmentStatus.CONFIRMED,
        clinic_name="Test Clinic",
    )
    mock_appointment_repo.get_appointment_by_id.return_value = confirmed_request

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await expire_pending_request_job(confirmed_request.id)

            mock_appointment_repo.update_appointment_status.assert_not_called()
            mock_notification_service.notify_client_pending_request_expired.assert_not_called()


@pytest.mark.asyncio
async def test_expire_pending_request_job_expires_admin_created_without_proposal(
    mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Test that the expiry job now also expires a PENDING, admin-created invite that
    has no outstanding client counter-proposal (proposed_datetime=None) -- the client
    simply never answered the invite. Admin-track auto-CONFIRM is retired, so this
    case must expire symmetrically with the CLIENT-created self-booking case."""
    sample_appointment.proposed_datetime = None
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await expire_pending_request_job(sample_appointment.id)

            mock_appointment_repo.update_appointment_status.assert_called_once_with(
                sample_appointment.id,
                AppointmentStatus.EXPIRED,
                ANY,
            )
            mock_notification_service.notify_client_pending_request_expired.assert_called_once_with(
                sample_appointment
            )


@pytest.mark.asyncio
async def test_expire_pending_request_job_expires_admin_created_with_client_proposal(
    mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """New case: a PENDING+ADMIN appointment where the client proposed their own
    time (request_reschedule_by_client) and the admin never answered that
    counter-proposal must expire too, exactly like a self-booking request --
    status becomes EXPIRED and the outstanding proposal fields are cleared."""
    admin_invite_with_counter = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        clinic_name="Test Clinic",
        proposed_datetime=(_current_tashkent_time() + timedelta(days=1)).isoformat(),
        proposed_by=CreatedBy.CLIENT,
        proposal_message_id=555,
    )
    mock_appointment_repo.get_appointment_by_id.return_value = admin_invite_with_counter
    mock_user_repo.get_client_by_id.return_value = MagicMock(telegram_user_id=12345)
    mock_notification_service.notify_client_pending_request_expired = AsyncMock(return_value=True)

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await expire_pending_request_job(admin_invite_with_counter.id)

            mock_appointment_repo.update_appointment_status.assert_called_once_with(
                admin_invite_with_counter.id,
                AppointmentStatus.EXPIRED,
                ANY,
            )
            mock_notification_service.notify_client_pending_request_expired.assert_called_once_with(
                admin_invite_with_counter
            )
            mock_appointment_repo.update_proposed_datetime.assert_called_once_with(
                admin_invite_with_counter.id, None
            )
            mock_appointment_repo.update_proposal_message_id.assert_called_once_with(
                admin_invite_with_counter.id, None
            )
            mock_appointment_repo.update_proposed_by.assert_called_once_with(
                admin_invite_with_counter.id, None
            )


@pytest.mark.asyncio
async def test_expire_pending_request_job_handles_missing_appointment(
    mock_appointment_repo, mock_user_repo, mock_notification_service
):
    """Test that the expiry job handles the case where the appointment is not found."""
    mock_appointment_repo.get_appointment_by_id.return_value = None

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            # Should not raise error
            await expire_pending_request_job(999)

            mock_appointment_repo.update_appointment_status.assert_not_called()
            mock_notification_service.notify_client_pending_request_expired.assert_not_called()


@pytest.mark.asyncio
async def test_expire_pending_request_job_handles_notification_failure(
    mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Test that the expiry job still cancels the appointment even if the client
    notification fails."""
    client_request = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=AppointmentStatus.PENDING,
        clinic_name="Test Clinic",
    )
    mock_appointment_repo.get_appointment_by_id.return_value = client_request
    mock_notification_service.notify_client_pending_request_expired = AsyncMock(
        side_effect=Exception("Network error")
    )

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            # Should not raise error even if notification fails
            await expire_pending_request_job(client_request.id)

            mock_appointment_repo.update_appointment_status.assert_called_once_with(
                client_request.id,
                AppointmentStatus.EXPIRED,
                ANY,
            )


# Phase 2a-bis: Proposal Reminder Tests (fires 3h before the proposed datetime)


@pytest.mark.asyncio
async def test_schedule_proposal_reminder_creates_job(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that scheduling a proposal reminder creates exactly 1 job with the
    correct job ID."""
    scheduler.start()

    await appointment_scheduler.schedule_proposal_reminder(sample_appointment)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == f"appt_{sample_appointment.id}_propose_reminder"

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_proposal_reminder_time_calculated_correctly(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that the proposal reminder runs 3 hours before appointment.datetime
    (i.e. the proposed datetime, since callers pass a proposal_target with
    datetime=proposed_datetime)."""
    scheduler.start()

    expected_reminder_time = datetime.fromisoformat(sample_appointment.datetime) - timedelta(hours=3)

    await appointment_scheduler.schedule_proposal_reminder(sample_appointment)

    jobs = scheduler.get_jobs()
    actual_reminder_time = jobs[0].next_run_time

    if actual_reminder_time.tzinfo:
        expected_reminder_time = expected_reminder_time.replace(tzinfo=actual_reminder_time.tzinfo)

    assert abs(
        (actual_reminder_time - expected_reminder_time).total_seconds()
    ) < 1

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_due_proposal_reminder_not_scheduled(
    appointment_scheduler, scheduler, sample_appointment
):
    """When the reminder time (datetime - 3h) is already in the past, no
    proposal reminder job should be scheduled."""
    scheduler.start()

    sample_appointment.datetime = (_current_tashkent_time() + timedelta(hours=1)).isoformat()

    await appointment_scheduler.schedule_proposal_reminder(sample_appointment)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_due_proposal_reminder_scheduling_does_not_call_add_job(
    appointment_scheduler, scheduler, sample_appointment
):
    """Regression test for the past-due guard: add_job must not be invoked
    when the reminder time is already in the past."""
    scheduler.start()

    sample_appointment.datetime = (_current_tashkent_time() + timedelta(minutes=30)).isoformat()

    with patch.object(scheduler, "add_job") as mock_add_job:
        await appointment_scheduler.schedule_proposal_reminder(sample_appointment)

        mock_add_job.assert_not_called()

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_proposal_reminder_skipped_while_pending_expiry_still_scheduled(
    appointment_scheduler, scheduler, sample_appointment
):
    """Edge case asymmetry: with the appointment 2h15m out, pending expiry
    (T-2h) is not yet past-due and gets scheduled, but the proposal reminder
    (T-3h) is already past-due and gets skipped."""
    scheduler.start()

    sample_appointment.datetime = (
        _current_tashkent_time() + timedelta(hours=2, minutes=15)
    ).isoformat()

    await appointment_scheduler.schedule_pending_expiry(sample_appointment)
    assert len(scheduler.get_jobs()) == 1

    await appointment_scheduler.schedule_proposal_reminder(sample_appointment)
    assert len(scheduler.get_jobs()) == 1
    assert scheduler.get_jobs()[0].id == f"appt_{sample_appointment.id}_expire"

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_proposal_reminder_silently_skipped_for_2h30_to_2h59_lead_time_window(
    appointment_scheduler, scheduler, sample_appointment
):
    """Documented, expected (non-buggy) behavior from the zombie-PENDING fix
    design (docs/zombie_pending_fix_prompt.md, point 5): a target datetime
    between 2h30 (the validation floor) and 2h59 away passes MIN_LEAD_TIME
    validation at the service layer, but the reminder's own '-3h' arithmetic
    is already past-due by the time schedule_proposal_reminder runs. It must
    be silently skipped -- no job, no exception -- since safety is already
    covered by the main timer plus the synchronous notification sent at
    proposal time, not by this reminder."""
    scheduler.start()

    sample_appointment.datetime = (
        _current_tashkent_time() + timedelta(hours=2, minutes=45)
    ).isoformat()

    await appointment_scheduler.schedule_proposal_reminder(sample_appointment)

    assert scheduler.get_jobs() == []

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_proposal_reminder_removes_job(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that cancelling a proposal reminder removes the scheduled job."""
    scheduler.start()

    await appointment_scheduler.schedule_proposal_reminder(sample_appointment)
    assert len(scheduler.get_jobs()) == 1

    await appointment_scheduler.cancel_proposal_reminder(sample_appointment.id)
    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_proposal_reminder_idempotent_no_error(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that cancelling a non-existent proposal reminder doesn't raise error."""
    scheduler.start()

    # Cancel a proposal reminder that was never scheduled
    await appointment_scheduler.cancel_proposal_reminder(999)

    # Should not raise error
    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_proposal_reminder_full_scenario_cancelled_before_firing(
    appointment_scheduler, scheduler, sample_appointment
):
    """Full scenario: admin proposes a new time -> proposal reminder is scheduled
    for proposed_dt - 3h -> client resolves the proposal (accept/reject) before
    the reminder fires -> cancel_proposal_reminder removes the job so it never runs."""
    scheduler.start()

    proposed_dt = _current_tashkent_time() + timedelta(days=3)
    sample_appointment.proposed_datetime = proposed_dt.isoformat()
    sample_appointment.proposed_by = CreatedBy.ADMIN
    proposal_target = replace(sample_appointment, datetime=sample_appointment.proposed_datetime)

    # Admin proposes a new time -> handler schedules the reminder against proposal_target
    await appointment_scheduler.schedule_proposal_reminder(proposal_target)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    job_id = f"appt_{sample_appointment.id}_propose_reminder"
    assert jobs[0].id == job_id

    expected_reminder_time = proposed_dt - timedelta(hours=3)
    actual_reminder_time = jobs[0].next_run_time
    if actual_reminder_time.tzinfo:
        expected_reminder_time = expected_reminder_time.replace(tzinfo=actual_reminder_time.tzinfo)
    assert abs((actual_reminder_time - expected_reminder_time).total_seconds()) < 1

    # Client accepts/rejects the proposal before the reminder fires -> handler
    # cancels the pending reminder job (same as cancel_pending_expiry).
    await appointment_scheduler.cancel_proposal_reminder(sample_appointment.id)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.fixture
def proposal_reminder_request(sample_appointment):
    """A PENDING self-booking request with an outstanding admin-proposed time,
    eligible for send_proposal_reminder_job."""
    return Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=AppointmentStatus.PENDING,
        clinic_name="Test Clinic",
        proposed_datetime=(datetime.now() + timedelta(days=3)).isoformat(),
        proposed_by=CreatedBy.ADMIN,
    )


@pytest.mark.asyncio
async def test_send_proposal_reminder_job_notifies_if_pending_and_proposed_by_admin(
    mock_appointment_repo, mock_user_repo, mock_notification_service, proposal_reminder_request
):
    """Test that the reminder job notifies the client for a still-PENDING request
    with an outstanding admin proposal."""
    mock_appointment_repo.get_appointment_by_id.return_value = proposal_reminder_request
    mock_notification_service.notify_client_proposal_reminder = AsyncMock(return_value=True)

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await send_proposal_reminder_job(proposal_reminder_request.id)

            mock_notification_service.notify_client_proposal_reminder.assert_called_once_with(
                proposal_reminder_request
            )


@pytest.mark.asyncio
async def test_send_proposal_reminder_job_handles_missing_appointment(
    mock_appointment_repo, mock_user_repo, mock_notification_service
):
    """Test that the reminder job silently returns when the appointment is not found."""
    mock_appointment_repo.get_appointment_by_id.return_value = None

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            # Should not raise error
            await send_proposal_reminder_job(999)

            mock_notification_service.notify_client_proposal_reminder.assert_not_called()


@pytest.mark.asyncio
async def test_send_proposal_reminder_job_redirects_to_reschedule_reminder_if_confirmed(
    mock_appointment_repo, mock_user_repo, mock_notification_service, proposal_reminder_request
):
    """Test that a request that turned CONFIRMED before the reminder fired now
    dispatches to the CONFIRMED-specific reschedule reminder instead of the
    PENDING-specific proposal reminder (bidirectional reminder covers both)."""
    proposal_reminder_request.status = AppointmentStatus.CONFIRMED
    mock_appointment_repo.get_appointment_by_id.return_value = proposal_reminder_request
    mock_notification_service.notify_client_appointment_reschedule_reminder = AsyncMock(return_value=True)

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await send_proposal_reminder_job(proposal_reminder_request.id)

            mock_notification_service.notify_client_proposal_reminder.assert_not_called()
            mock_notification_service.notify_client_appointment_reschedule_reminder.assert_called_once_with(
                proposal_reminder_request
            )


@pytest.mark.asyncio
async def test_send_proposal_reminder_job_notifies_regardless_of_created_by(
    mock_appointment_repo, mock_user_repo, mock_notification_service, proposal_reminder_request
):
    """Test that the reminder job no longer excludes admin-created requests --
    dispatch depends only on proposed_by/status, not created_by."""
    proposal_reminder_request.created_by = CreatedBy.ADMIN
    mock_appointment_repo.get_appointment_by_id.return_value = proposal_reminder_request
    mock_notification_service.notify_client_proposal_reminder = AsyncMock(return_value=True)

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await send_proposal_reminder_job(proposal_reminder_request.id)

            mock_notification_service.notify_client_proposal_reminder.assert_called_once_with(
                proposal_reminder_request
            )


@pytest.mark.asyncio
async def test_send_proposal_reminder_job_skips_if_no_proposed_datetime(
    mock_appointment_repo, mock_user_repo, mock_notification_service, proposal_reminder_request
):
    """Test that the reminder job skips a request with no outstanding proposal."""
    proposal_reminder_request.proposed_datetime = None
    mock_appointment_repo.get_appointment_by_id.return_value = proposal_reminder_request

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await send_proposal_reminder_job(proposal_reminder_request.id)

            mock_notification_service.notify_client_proposal_reminder.assert_not_called()


@pytest.mark.asyncio
async def test_send_proposal_reminder_job_dispatches_client_proposal_to_admin_reminder(
    mock_appointment_repo, mock_user_repo, mock_notification_service, proposal_reminder_request
):
    """Test that a request whose outstanding proposal was made by the client
    dispatches to the admin-facing reminder instead of the client-facing one --
    the recipient is always whichever side is NOT proposed_by."""
    proposal_reminder_request.proposed_by = CreatedBy.CLIENT
    proposal_reminder_request.doctor_id = 42
    mock_appointment_repo.get_appointment_by_id.return_value = proposal_reminder_request
    mock_user_repo.get_user_by_id.return_value = User(
        ID=42, full_name="Test Doctor", phone="+998907654321", role=Role.ADMIN, telegram_user_id=54321,
    )
    mock_notification_service.notify_admin_proposal_reminder = AsyncMock()

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await send_proposal_reminder_job(proposal_reminder_request.id)

            mock_notification_service.notify_client_proposal_reminder.assert_not_called()
            mock_notification_service.notify_admin_proposal_reminder.assert_called_once_with(
                54321, proposal_reminder_request
            )


@pytest.mark.asyncio
async def test_send_proposal_reminder_job_dispatches_confirmed_client_reschedule_to_admin_reminder(
    mock_appointment_repo, mock_user_repo, mock_notification_service, proposal_reminder_request
):
    """Fourth and last negotiation direction: a CONFIRMED appointment with a
    client-requested reschedule outstanding (proposed_by=CLIENT) must remind
    the ADMIN side, not the client -- the same admin-facing reminder used for
    the PENDING+admin-invite-countered-by-client direction, since the
    recipient is always whichever side is NOT proposed_by, regardless of
    status."""
    proposal_reminder_request.status = AppointmentStatus.CONFIRMED
    proposal_reminder_request.proposed_by = CreatedBy.CLIENT
    proposal_reminder_request.doctor_id = 42
    mock_appointment_repo.get_appointment_by_id.return_value = proposal_reminder_request
    mock_user_repo.get_user_by_id.return_value = User(
        ID=42, full_name="Test Doctor", phone="+998907654321", role=Role.ADMIN, telegram_user_id=54321,
    )
    mock_notification_service.notify_admin_proposal_reminder = AsyncMock()

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await send_proposal_reminder_job(proposal_reminder_request.id)

            mock_notification_service.notify_client_proposal_reminder.assert_not_called()
            mock_notification_service.notify_client_appointment_reschedule_reminder.assert_not_called()
            mock_notification_service.notify_admin_proposal_reminder.assert_called_once_with(
                54321, proposal_reminder_request
            )


@pytest.fixture
def sample_reschedule_appointment(sample_appointment):
    """A CONFIRMED appointment with an outstanding client-initiated reschedule request.

    The proposed datetime is deliberately different from the original datetime so
    tests can detect if scheduling accidentally anchors to the wrong field.
    """
    now = datetime.now()
    sample_appointment.status = AppointmentStatus.CONFIRMED
    sample_appointment.created_by = CreatedBy.CLIENT
    sample_appointment.proposed_datetime = (now + timedelta(days=5)).isoformat()
    sample_appointment.proposed_by = CreatedBy.CLIENT
    return sample_appointment


@pytest.mark.asyncio
async def test_schedule_reschedule_expiry_creates_job(
    appointment_scheduler, scheduler, sample_reschedule_appointment
):
    """Test that scheduling reschedule expiry creates exactly 1 job."""
    scheduler.start()

    await appointment_scheduler.schedule_reschedule_expiry(sample_reschedule_appointment)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == f"appt_{sample_reschedule_appointment.id}_resch_expire"

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_reschedule_expiry_job_id_correct(
    appointment_scheduler, scheduler, sample_reschedule_appointment
):
    """Test that reschedule expiry job ID follows pattern: appt_{id}_resch_expire."""
    scheduler.start()

    await appointment_scheduler.schedule_reschedule_expiry(sample_reschedule_appointment)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == f"appt_{sample_reschedule_appointment.id}_resch_expire"

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_reschedule_expiry_time_anchored_to_proposed_datetime_not_original(
    appointment_scheduler, scheduler, sample_reschedule_appointment
):
    """Test that reschedule expiry runs at the PROPOSED datetime, not the
    appointment's original datetime. The fixture deliberately sets these to
    different values so this assertion can fail if the wrong field is used."""
    scheduler.start()

    assert sample_reschedule_appointment.proposed_datetime != sample_reschedule_appointment.datetime

    expected_expiry_time = datetime.fromisoformat(sample_reschedule_appointment.proposed_datetime)

    await appointment_scheduler.schedule_reschedule_expiry(sample_reschedule_appointment)

    jobs = scheduler.get_jobs()
    actual_expiry_time = jobs[0].next_run_time

    if actual_expiry_time.tzinfo:
        expected_expiry_time = expected_expiry_time.replace(tzinfo=actual_expiry_time.tzinfo)

    assert abs(
        (actual_expiry_time - expected_expiry_time).total_seconds()
    ) < 1

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_reschedule_expiry_removes_job(
    appointment_scheduler, scheduler, sample_reschedule_appointment
):
    """Test that cancelling reschedule expiry removes the scheduled job."""
    scheduler.start()

    await appointment_scheduler.schedule_reschedule_expiry(sample_reschedule_appointment)
    assert len(scheduler.get_jobs()) == 1

    await appointment_scheduler.cancel_reschedule_expiry(sample_reschedule_appointment.id)
    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_reschedule_expiry_idempotent_no_error(
    appointment_scheduler, scheduler
):
    """Test that cancelling non-existent reschedule expiry doesn't raise error."""
    scheduler.start()

    # Cancel reschedule expiry that was never scheduled
    await appointment_scheduler.cancel_reschedule_expiry(999)

    # Should not raise error
    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_appointment_without_id_reschedule_expiry_not_scheduled(
    appointment_scheduler, scheduler, sample_reschedule_appointment
):
    """Test that appointments without ID are not scheduled for reschedule expiry."""
    scheduler.start()

    sample_reschedule_appointment.id = None
    await appointment_scheduler.schedule_reschedule_expiry(sample_reschedule_appointment)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_appointment_without_proposed_datetime_reschedule_expiry_not_scheduled(
    appointment_scheduler, scheduler, sample_reschedule_appointment
):
    """Test that appointments with no outstanding proposal are not scheduled
    for reschedule expiry (guard unique to schedule_reschedule_expiry)."""
    scheduler.start()

    sample_reschedule_appointment.proposed_datetime = None
    await appointment_scheduler.schedule_reschedule_expiry(sample_reschedule_appointment)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_due_reschedule_expiry_not_scheduled(
    appointment_scheduler, scheduler, sample_reschedule_appointment
):
    """When the proposed datetime is already in the past, no reschedule
    expiry job should be scheduled."""
    scheduler.start()

    sample_reschedule_appointment.proposed_datetime = (
        _current_tashkent_time() - timedelta(hours=1)
    ).isoformat()

    await appointment_scheduler.schedule_reschedule_expiry(sample_reschedule_appointment)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_due_reschedule_expiry_scheduling_does_not_call_add_job(
    appointment_scheduler, scheduler, sample_reschedule_appointment
):
    """Regression test for the past-due guard: add_job must not be invoked
    when the proposed datetime is already in the past."""
    scheduler.start()

    sample_reschedule_appointment.proposed_datetime = (
        _current_tashkent_time() - timedelta(minutes=30)
    ).isoformat()

    with patch.object(scheduler, "add_job") as mock_add_job:
        await appointment_scheduler.schedule_reschedule_expiry(sample_reschedule_appointment)

        mock_add_job.assert_not_called()

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_expire_reschedule_request_job_clears_proposal_if_confirmed_and_client_proposed(
    mock_appointment_repo, mock_user_repo, mock_notification_service, sample_reschedule_appointment
):
    """Test that the expiry job clears the outstanding client proposal but leaves
    the appointment's status untouched (it stays CONFIRMED at the ORIGINAL time)."""
    mock_appointment_repo.get_appointment_by_id.return_value = sample_reschedule_appointment
    mock_notification_service.notify_client_reschedule_request_expired = AsyncMock(return_value=True)

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await expire_reschedule_request_job(sample_reschedule_appointment.id)

            # Status must NOT change - the appointment stays CONFIRMED, unlike the pending job.
            mock_appointment_repo.update_appointment_status.assert_not_called()

            mock_appointment_repo.update_proposed_datetime.assert_called_once_with(
                sample_reschedule_appointment.id, None
            )
            mock_appointment_repo.update_proposed_by.assert_called_once_with(
                sample_reschedule_appointment.id, None
            )
            # Unlike the pending job, proposal_message_id is left untouched.
            mock_appointment_repo.update_proposal_message_id.assert_not_called()

            mock_notification_service.notify_client_reschedule_request_expired.assert_called_once_with(
                sample_reschedule_appointment
            )


@pytest.mark.asyncio
async def test_expire_reschedule_request_job_proceeds_regardless_of_status(
    mock_appointment_repo, mock_user_repo, mock_notification_service, sample_reschedule_appointment
):
    """PR3: the guard was generalized from `status != CONFIRMED or proposed_datetime
    is None or proposed_by != CLIENT` down to just `proposed_datetime is None` -- an
    outstanding proposal now expires the same way no matter what status the
    appointment is sitting in. This is a direct regression test for the removed
    status check (formerly named test_..._skips_if_not_confirmed, which asserted
    the opposite of current behavior)."""
    sample_reschedule_appointment.status = AppointmentStatus.CANCELLED
    mock_appointment_repo.get_appointment_by_id.return_value = sample_reschedule_appointment
    mock_notification_service.notify_client_reschedule_request_expired = AsyncMock(return_value=True)

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await expire_reschedule_request_job(sample_reschedule_appointment.id)

            mock_appointment_repo.update_appointment_status.assert_not_called()
            mock_appointment_repo.update_proposed_datetime.assert_called_once_with(
                sample_reschedule_appointment.id, None
            )
            mock_appointment_repo.update_proposed_by.assert_called_once_with(
                sample_reschedule_appointment.id, None
            )
            mock_notification_service.notify_client_reschedule_request_expired.assert_called_once_with(
                sample_reschedule_appointment
            )


@pytest.mark.asyncio
async def test_expire_reschedule_request_job_clears_proposal_for_pending_admin_created_counter_offer(
    mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """PR3: the guard's generalization specifically covers the new PENDING+ADMIN
    negotiation branch -- a client who countered an admin invite with their own
    time (proposed_by=CLIENT) and never got an answer has that proposal expired
    the same way a CONFIRMED-appointment negotiation would. The appointment stays
    PENDING at its original datetime; only the outstanding proposal is cleared.
    Restoring auto_confirm afterwards is a known, intentionally unimplemented gap
    (see the TODO in expire_reschedule_request_job) and is not asserted here."""
    sample_appointment.status = AppointmentStatus.PENDING
    sample_appointment.created_by = CreatedBy.ADMIN
    original_datetime = sample_appointment.datetime
    sample_appointment.proposed_datetime = (datetime.now() + timedelta(days=3)).isoformat()
    sample_appointment.proposed_by = CreatedBy.CLIENT
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment
    mock_notification_service.notify_client_reschedule_request_expired = AsyncMock(return_value=True)

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await expire_reschedule_request_job(sample_appointment.id)

            mock_appointment_repo.update_appointment_status.assert_not_called()
            mock_appointment_repo.update_proposed_datetime.assert_called_once_with(
                sample_appointment.id, None
            )
            mock_appointment_repo.update_proposed_by.assert_called_once_with(
                sample_appointment.id, None
            )
            mock_notification_service.notify_client_reschedule_request_expired.assert_called_once_with(
                sample_appointment
            )
            assert sample_appointment.status is AppointmentStatus.PENDING
            assert sample_appointment.datetime == original_datetime


@pytest.mark.asyncio
async def test_expire_reschedule_request_job_skips_if_no_proposed_datetime(
    mock_appointment_repo, mock_user_repo, mock_notification_service, sample_reschedule_appointment
):
    """Test that the expiry job skips an appointment with no outstanding proposal
    (e.g. it was already accepted/rejected/cancelled before the job ran)."""
    sample_reschedule_appointment.proposed_datetime = None
    mock_appointment_repo.get_appointment_by_id.return_value = sample_reschedule_appointment

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await expire_reschedule_request_job(sample_reschedule_appointment.id)

            mock_appointment_repo.update_proposed_datetime.assert_not_called()
            mock_appointment_repo.update_proposed_by.assert_not_called()
            mock_notification_service.notify_client_reschedule_request_expired.assert_not_called()


@pytest.mark.asyncio
async def test_expire_reschedule_request_job_also_expires_admin_proposed_counter_offer(
    mock_appointment_repo, mock_user_repo, mock_notification_service, sample_reschedule_appointment
):
    """PR2 Part 4: the job's guard no longer excludes admin-initiated counter-offers
    -- an unanswered admin proposal on a CONFIRMED appointment expires exactly like
    a client-initiated one (regression test for the removed `proposed_by != CLIENT`
    guard)."""
    sample_reschedule_appointment.proposed_by = CreatedBy.ADMIN
    mock_appointment_repo.get_appointment_by_id.return_value = sample_reschedule_appointment
    mock_notification_service.notify_client_reschedule_request_expired = AsyncMock(return_value=True)

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            await expire_reschedule_request_job(sample_reschedule_appointment.id)

            mock_appointment_repo.update_appointment_status.assert_not_called()
            mock_appointment_repo.update_proposed_datetime.assert_called_once_with(
                sample_reschedule_appointment.id, None
            )
            mock_appointment_repo.update_proposed_by.assert_called_once_with(
                sample_reschedule_appointment.id, None
            )
            mock_notification_service.notify_client_reschedule_request_expired.assert_called_once_with(
                sample_reschedule_appointment
            )


@pytest.mark.asyncio
async def test_expire_reschedule_request_job_handles_missing_appointment(
    mock_appointment_repo, mock_user_repo, mock_notification_service
):
    """Test that the expiry job handles the case where the appointment is not found."""
    mock_appointment_repo.get_appointment_by_id.return_value = None

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            # Should not raise error
            await expire_reschedule_request_job(999)

            mock_appointment_repo.update_proposed_datetime.assert_not_called()
            mock_appointment_repo.update_proposed_by.assert_not_called()
            mock_notification_service.notify_client_reschedule_request_expired.assert_not_called()


@pytest.mark.asyncio
async def test_expire_reschedule_request_job_handles_notification_failure(
    mock_appointment_repo, mock_user_repo, mock_notification_service, sample_reschedule_appointment
):
    """Test that the expiry job still clears the proposal even if the client
    notification fails."""
    mock_appointment_repo.get_appointment_by_id.return_value = sample_reschedule_appointment
    mock_notification_service.notify_client_reschedule_request_expired = AsyncMock(
        side_effect=Exception("Network error")
    )

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class, \
             patch("bot.services.appointment.appointment_jobs.UserRepository") as mock_user_repo_class, \
             patch("bot.services.appointment.appointment_jobs.AppointmentNotificationService") as mock_notif_class:

            mock_repo_class.return_value = mock_appointment_repo
            mock_user_repo_class.return_value = mock_user_repo
            mock_notif_class.return_value = mock_notification_service

            # Should not raise error even if notification fails
            await expire_reschedule_request_job(sample_reschedule_appointment.id)

            mock_appointment_repo.update_proposed_datetime.assert_called_once_with(
                sample_reschedule_appointment.id, None
            )
            mock_appointment_repo.update_proposed_by.assert_called_once_with(
                sample_reschedule_appointment.id, None
            )


# Auto-Confirm Tests: PENDING -> CONFIRMED 2h before appointment (admin-created only)


@pytest.mark.asyncio
async def test_schedule_auto_confirm_creates_job(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that scheduling auto-confirm creates exactly 1 job for an
    admin-created PENDING appointment."""
    scheduler.start()

    await appointment_scheduler.schedule_auto_confirm(sample_appointment)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == f"appt_{sample_appointment.id}_autoconf"

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_auto_confirm_time_calculated_correctly(
    appointment_scheduler, scheduler, sample_appointment
):
    """[LEGACY] Test that auto-confirm timing is calculated correctly (2 hours before).

    This tests the legacy auto-confirm mechanism, which is no longer scheduled
    for new appointments but is tested for backward compatibility."""
    scheduler.start()

    appointment_dt = datetime.fromisoformat(sample_appointment.datetime)
    expected_autoconf_time = appointment_dt - timedelta(hours=2)

    await appointment_scheduler.schedule_auto_confirm(sample_appointment)

    jobs = scheduler.get_jobs()
    actual_autoconf_time = jobs[0].next_run_time

    if actual_autoconf_time.tzinfo:
        expected_autoconf_time = expected_autoconf_time.replace(tzinfo=actual_autoconf_time.tzinfo)

    assert abs(
        (actual_autoconf_time - expected_autoconf_time).total_seconds()
    ) < 1

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_auto_confirm_removes_job(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that cancelling auto-confirm removes the scheduled job."""
    scheduler.start()

    await appointment_scheduler.schedule_auto_confirm(sample_appointment)
    assert len(scheduler.get_jobs()) == 1

    await appointment_scheduler.cancel_auto_confirm(sample_appointment.id)
    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_auto_confirm_idempotent_no_error(
    appointment_scheduler, scheduler
):
    """Test that cancelling non-existent auto-confirm doesn't raise error."""
    scheduler.start()

    await appointment_scheduler.cancel_auto_confirm(999)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_appointment_without_id_auto_confirm_not_scheduled(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that appointments without ID are not scheduled for auto-confirm."""
    scheduler.start()

    sample_appointment.id = None
    await appointment_scheduler.schedule_auto_confirm(sample_appointment)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_schedule_auto_confirm_skips_if_not_pending(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test that auto-confirm is not scheduled for a non-PENDING appointment."""
    scheduler.start()

    sample_appointment.status = AppointmentStatus.CONFIRMED
    await appointment_scheduler.schedule_auto_confirm(sample_appointment)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_schedule_auto_confirm_skips_if_not_admin_created(
    appointment_scheduler, scheduler, sample_appointment
):
    """[LEGACY] Test that auto-confirm is not scheduled for client self-booking.

    Verifies the legacy auto-confirm mechanism only applies to admin-created
    appointments. Note: auto-confirm is no longer used for new appointments —
    both CLIENT and ADMIN tracks now expire via pending_expiry if unanswered."""
    scheduler.start()

    sample_appointment.created_by = CreatedBy.CLIENT
    await appointment_scheduler.schedule_auto_confirm(sample_appointment)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_due_auto_confirm_not_scheduled(
    appointment_scheduler, scheduler, sample_appointment
):
    """When the auto-confirm time (2h before appointment) is already in the
    past, no job should be scheduled."""
    scheduler.start()

    sample_appointment.datetime = (_current_tashkent_time() + timedelta(hours=1)).isoformat()

    await appointment_scheduler.schedule_auto_confirm(sample_appointment)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_due_auto_confirm_scheduling_does_not_call_add_job(
    appointment_scheduler, scheduler, sample_appointment
):
    """Regression test for the past-due guard: add_job must not be invoked
    when the computed auto-confirm time is already in the past."""
    scheduler.start()

    sample_appointment.datetime = (_current_tashkent_time() + timedelta(minutes=30)).isoformat()

    with patch.object(scheduler, "add_job") as mock_add_job:
        await appointment_scheduler.schedule_auto_confirm(sample_appointment)

        mock_add_job.assert_not_called()

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_auto_confirm_pending_job_confirms_if_pending_and_admin_created(
    mock_appointment_repo, sample_appointment
):
    """[LEGACY] Test that legacy auto-confirm job transitions PENDING to CONFIRMED.

    Tests the deprecated auto-confirm mechanism for backward compatibility.
    New appointments no longer use auto-confirm — both CLIENT and ADMIN tracks
    expire via pending_expiry if unanswered."""
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class:
            mock_repo_class.return_value = mock_appointment_repo

            await auto_confirm_pending_job(sample_appointment.id)

            mock_appointment_repo.update_appointment_status.assert_called_once_with(
                sample_appointment.id,
                AppointmentStatus.CONFIRMED,
                ANY,
            )


@pytest.mark.asyncio
async def test_auto_confirm_pending_job_skips_if_not_pending(
    mock_appointment_repo, sample_appointment
):
    """Test that the auto-confirm job skips an appointment that is no longer
    PENDING (e.g. already cancelled by the client before the job fired)."""
    cancelled_appointment = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.CANCELLED,
        clinic_name="Test Clinic",
    )
    mock_appointment_repo.get_appointment_by_id.return_value = cancelled_appointment

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class:
            mock_repo_class.return_value = mock_appointment_repo

            await auto_confirm_pending_job(cancelled_appointment.id)

            mock_appointment_repo.update_appointment_status.assert_not_called()


@pytest.mark.asyncio
async def test_auto_confirm_pending_job_skips_if_not_admin_created(
    mock_appointment_repo, sample_appointment
):
    """Test that the auto-confirm job never confirms a client self-booking
    request, even if it is still PENDING when the job fires. This guards
    against a stray job (e.g. left over from before this guard existed)
    silently confirming a request the clinic never approved."""
    client_request = Appointment(
        id=1,
        clinic_id=1,
        client_id=1,
        datetime=sample_appointment.datetime,
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=AppointmentStatus.PENDING,
        clinic_name="Test Clinic",
    )
    mock_appointment_repo.get_appointment_by_id.return_value = client_request

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class:
            mock_repo_class.return_value = mock_appointment_repo

            await auto_confirm_pending_job(client_request.id)

            mock_appointment_repo.update_appointment_status.assert_not_called()


@pytest.mark.asyncio
async def test_auto_confirm_pending_job_handles_missing_appointment(
    mock_appointment_repo,
):
    """Test that the auto-confirm job handles the case where the appointment
    is not found."""
    mock_appointment_repo.get_appointment_by_id.return_value = None

    with patch("bot.services.appointment.appointment_jobs.get_bot") as mock_get_bot, \
         patch("bot.services.appointment.appointment_jobs.load_config") as mock_load_config, \
         patch("bot.services.appointment.appointment_jobs.Database") as mock_db_class:

        mock_get_bot.return_value = AsyncMock()
        mock_load_config.return_value = MagicMock(database_path=":memory:")

        mock_connection = AsyncMock()
        mock_db_instance = MagicMock()
        mock_db_instance.connect = AsyncMock(return_value=mock_connection)
        mock_db_class.return_value = mock_db_instance

        with patch("bot.services.appointment.appointment_jobs.AppointmentRepository") as mock_repo_class:
            mock_repo_class.return_value = mock_appointment_repo

            # Should not raise error
            await auto_confirm_pending_job(999)

            mock_appointment_repo.update_appointment_status.assert_not_called()


# --- Regression: users.created_at timezone migration must not disturb the
# APScheduler job store. schedule_* only ever touches the in-memory
# AsyncIOScheduler job store (appointment jobs), while the migration script
# only ever touches the on-disk `users` table via plain sqlite3 -- these are
# fully independent, but the customer explicitly asked for this to be
# proven, not merely assumed from "they're in different files".
@pytest.mark.asyncio
async def test_users_created_at_migration_does_not_disturb_scheduled_jobs(
    appointment_scheduler, scheduler, sample_appointment
):
    """Running scripts/migrate_users_created_at_timezone.py against a users
    table must leave every already-scheduled APScheduler job (id and
    next_run_time) completely untouched."""
    scheduler.start()

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)
    await appointment_scheduler.schedule_pending_expiry(sample_appointment)

    jobs_before = {job.id: job.next_run_time for job in scheduler.get_jobs()}
    assert len(jobs_before) == 3

    # Actually exercise the real migration against a real users table, in
    # a temp cwd, to formally prove there is no interaction with the
    # scheduler's job store (which lives entirely in-process/in-memory
    # here, not on disk).
    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.chdir(tmp_dir)
        try:
            connection = await aiosqlite.connect(str(Path(tmp_dir) / "migration_users.db"))
            try:
                await connection.execute(
                    "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
                )
                user_repo = UserRepository(connection)
                await user_repo.init()

                await user_repo.create_user(
                    User(
                        full_name="Иванов Иван",
                        phone="+998901234567",
                        role=Role.CLIENT,
                        telegram_user_id=1001,
                        created_at=get_current_tashkent_time(),
                    )
                )
            finally:
                await connection.close()

            db_path = Path(tmp_dir) / "data" / "data_base.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            sync_conn = sqlite3.connect(db_path)
            try:
                sync_conn.execute(
                    "CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT)"
                )
                sync_conn.execute(
                    "INSERT INTO users(created_at) VALUES ('2026-01-01 10:00:00')"
                )
                sync_conn.commit()
            finally:
                sync_conn.close()

            migrate_users_created_at()

            verify_conn = sqlite3.connect(db_path)
            try:
                migrated_value = verify_conn.execute(
                    "SELECT created_at FROM users"
                ).fetchone()[0]
            finally:
                verify_conn.close()

            # Migration must have actually done real work, not been a no-op.
            assert migrated_value == "2026-01-01 15:00:00"
        finally:
            os.chdir(original_cwd)

    jobs_after = {job.id: job.next_run_time for job in scheduler.get_jobs()}

    assert jobs_after == jobs_before

    scheduler.shutdown(wait=False)


# --- resync_appointment_jobs: single source of truth for the full job set ---
# Recomputes ALL job kinds (pending_expiry, proposal_reminder, auto_confirm,
# reschedule_expiry, appointment_reminders, appointment_completions) from
# status/created_by/proposed_datetime/proposed_by in one call, replacing the
# ad-hoc per-handler cancel/schedule sequences used elsewhere.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "terminal_status",
    [
        AppointmentStatus.CANCELLED,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.NO_SHOW,
        AppointmentStatus.EXPIRED,
    ],
)
async def test_resync_appointment_jobs_terminal_status_cancels_everything(
    appointment_scheduler, scheduler, sample_appointment, terminal_status
):
    """Any terminal status must cancel every kind of job that might already be
    scheduled and must not schedule anything new."""
    scheduler.start()

    sample_appointment.status = AppointmentStatus.PENDING
    sample_appointment.created_by = CreatedBy.CLIENT
    await appointment_scheduler.schedule_pending_expiry(sample_appointment)
    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)
    assert len(scheduler.get_jobs()) == 3

    sample_appointment.status = terminal_status

    with patch.object(scheduler, "add_job") as mock_add_job:
        await appointment_scheduler.resync_appointment_jobs(sample_appointment)

        mock_add_job.assert_not_called()

    assert scheduler.get_jobs() == []

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_resync_appointment_jobs_confirmed_without_proposal_schedules_reminders_and_completion(
    appointment_scheduler, scheduler, sample_appointment
):
    """CONFIRMED with no outstanding proposal: only reminders + completion are
    scheduled; the PENDING-only and reschedule-negotiation jobs are absent."""
    scheduler.start()

    sample_appointment.status = AppointmentStatus.CONFIRMED
    sample_appointment.proposed_datetime = None

    await appointment_scheduler.resync_appointment_jobs(sample_appointment)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        f"appt_{sample_appointment.id}_24h",
        f"appt_{sample_appointment.id}_2h",
        f"appt_{sample_appointment.id}_complete",
    }

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_resync_appointment_jobs_confirmed_with_proposal_also_schedules_reschedule_expiry(
    appointment_scheduler, scheduler, sample_appointment
):
    """CONFIRMED with a client-initiated proposal outstanding: reschedule_expiry
    and the bidirectional proposal reminder are added on top of
    reminders/completion -- and reminders/completion still run against the
    ORIGINAL datetime, since nothing has been agreed yet."""
    scheduler.start()

    sample_appointment.status = AppointmentStatus.CONFIRMED
    original_datetime = sample_appointment.datetime
    proposed_dt = _current_tashkent_time() + timedelta(days=5)
    sample_appointment.proposed_datetime = proposed_dt.isoformat()
    sample_appointment.proposed_by = CreatedBy.CLIENT

    await appointment_scheduler.resync_appointment_jobs(sample_appointment)

    jobs = {job.id: job.next_run_time for job in scheduler.get_jobs()}
    assert set(jobs) == {
        f"appt_{sample_appointment.id}_24h",
        f"appt_{sample_appointment.id}_2h",
        f"appt_{sample_appointment.id}_complete",
        f"appt_{sample_appointment.id}_resch_expire",
        f"appt_{sample_appointment.id}_propose_reminder",
    }

    expected_24h = datetime.fromisoformat(original_datetime) - timedelta(hours=24)
    actual_24h = jobs[f"appt_{sample_appointment.id}_24h"]
    if actual_24h.tzinfo:
        expected_24h = expected_24h.replace(tzinfo=actual_24h.tzinfo)
    assert abs((actual_24h - expected_24h).total_seconds()) < 1

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_resync_appointment_jobs_confirmed_with_admin_proposal_also_schedules_reschedule_expiry(
    appointment_scheduler, scheduler, sample_appointment
):
    """Symmetric case for PR2 Part 2 (admin proposes a new time for a CONFIRMED
    appointment): the CONFIRMED branch of resync_appointment_jobs does not branch
    on proposed_by, so an admin-initiated proposal must schedule the exact same
    job set as a client-initiated one (reminders/completion against the ORIGINAL
    datetime, plus reschedule_expiry)."""
    scheduler.start()

    sample_appointment.status = AppointmentStatus.CONFIRMED
    original_datetime = sample_appointment.datetime
    proposed_dt = _current_tashkent_time() + timedelta(days=5)
    sample_appointment.proposed_datetime = proposed_dt.isoformat()
    sample_appointment.proposed_by = CreatedBy.ADMIN

    await appointment_scheduler.resync_appointment_jobs(sample_appointment)

    jobs = {job.id: job.next_run_time for job in scheduler.get_jobs()}
    assert set(jobs) == {
        f"appt_{sample_appointment.id}_24h",
        f"appt_{sample_appointment.id}_2h",
        f"appt_{sample_appointment.id}_complete",
        f"appt_{sample_appointment.id}_resch_expire",
        f"appt_{sample_appointment.id}_propose_reminder",
    }

    expected_24h = datetime.fromisoformat(original_datetime) - timedelta(hours=24)
    actual_24h = jobs[f"appt_{sample_appointment.id}_24h"]
    if actual_24h.tzinfo:
        expected_24h = expected_24h.replace(tzinfo=actual_24h.tzinfo)
    assert abs((actual_24h - expected_24h).total_seconds()) < 1

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_resync_appointment_jobs_pending_client_no_proposal_schedules_pending_expiry_only(
    appointment_scheduler, scheduler, sample_appointment
):
    """PENDING self-booking (created_by=CLIENT) with no counter-proposal from
    the clinic: only pending_expiry is scheduled, relative to the appointment's
    own requested datetime."""
    scheduler.start()

    sample_appointment.status = AppointmentStatus.PENDING
    sample_appointment.created_by = CreatedBy.CLIENT
    sample_appointment.proposed_datetime = None

    await appointment_scheduler.resync_appointment_jobs(sample_appointment)

    jobs = {job.id: job.next_run_time for job in scheduler.get_jobs()}
    assert set(jobs) == {f"appt_{sample_appointment.id}_expire"}

    expected_expiry = datetime.fromisoformat(sample_appointment.datetime) - timedelta(hours=2)
    actual_expiry = jobs[f"appt_{sample_appointment.id}_expire"]
    if actual_expiry.tzinfo:
        expected_expiry = expected_expiry.replace(tzinfo=actual_expiry.tzinfo)
    assert abs((actual_expiry - expected_expiry).total_seconds()) < 1

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_resync_appointment_jobs_pending_client_admin_proposal_anchors_to_proposed_datetime(
    appointment_scheduler, scheduler, sample_appointment
):
    """PENDING self-booking with a clinic counter-proposal outstanding
    (proposed_datetime + proposed_by=ADMIN): pending_expiry AND proposal_reminder
    must both be computed against the PROPOSED datetime, not the original
    appointment.datetime -- this is the discriminating case for the
    replace(appointment, datetime=proposed_datetime) redirection."""
    scheduler.start()

    sample_appointment.status = AppointmentStatus.PENDING
    sample_appointment.created_by = CreatedBy.CLIENT
    proposed_dt = _current_tashkent_time() + timedelta(days=5)
    sample_appointment.proposed_datetime = proposed_dt.isoformat()
    sample_appointment.proposed_by = CreatedBy.ADMIN

    await appointment_scheduler.resync_appointment_jobs(sample_appointment)

    jobs = {job.id: job.next_run_time for job in scheduler.get_jobs()}
    assert set(jobs) == {
        f"appt_{sample_appointment.id}_expire",
        f"appt_{sample_appointment.id}_propose_reminder",
    }

    expected_expiry = proposed_dt - timedelta(hours=2)
    expected_reminder = proposed_dt - timedelta(hours=3)

    actual_expiry = jobs[f"appt_{sample_appointment.id}_expire"]
    actual_reminder = jobs[f"appt_{sample_appointment.id}_propose_reminder"]

    if actual_expiry.tzinfo:
        expected_expiry = expected_expiry.replace(tzinfo=actual_expiry.tzinfo)
    if actual_reminder.tzinfo:
        expected_reminder = expected_reminder.replace(tzinfo=actual_reminder.tzinfo)

    assert abs((actual_expiry - expected_expiry).total_seconds()) < 1
    assert abs((actual_reminder - expected_reminder).total_seconds()) < 1

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_resync_appointment_jobs_pending_admin_created_no_proposal_schedules_pending_expiry_only(
    appointment_scheduler, scheduler, sample_appointment
):
    """PENDING appointment created by the ADMIN with no outstanding client
    counter-proposal (ordinary unanswered invite): pending_expiry is scheduled
    against the appointment's own datetime, exactly like a CLIENT self-booking
    request with no counter. Admin-track auto-CONFIRM is retired -- both tracks
    now resolve to EXPIRED symmetrically on timeout."""
    scheduler.start()

    sample_appointment.status = AppointmentStatus.PENDING
    sample_appointment.created_by = CreatedBy.ADMIN

    await appointment_scheduler.resync_appointment_jobs(sample_appointment)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {f"appt_{sample_appointment.id}_expire"}

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_resync_appointment_jobs_pending_admin_created_with_proposal_anchors_to_proposed_datetime(
    appointment_scheduler, scheduler, sample_appointment
):
    """PENDING+ADMIN with a client counter-proposal outstanding must NOT keep ticking
    towards auto_confirm (retired) or stay anchored to the STALE original datetime.
    The clinic needs to decide on the client's proposed time; if it doesn't, the
    request expires relative to the PROPOSED datetime -- recomputed on this very
    resync, not left over from an earlier schedule -- and the bidirectional proposal
    reminder is scheduled against that same target. No auto_confirm and no
    reschedule_expiry job may remain.

    Pre-seeds a real pending_expiry job first (via a first resync with no proposal)
    so this proves the job is actively CANCELLED and RESCHEDULED by the second
    resync, not merely absent because it was never created."""
    scheduler.start()

    sample_appointment.status = AppointmentStatus.PENDING
    sample_appointment.created_by = CreatedBy.ADMIN
    sample_appointment.proposed_datetime = None

    await appointment_scheduler.resync_appointment_jobs(sample_appointment)
    assert {job.id for job in scheduler.get_jobs()} == {f"appt_{sample_appointment.id}_expire"}

    proposed_dt = _current_tashkent_time() + timedelta(days=5)
    sample_appointment.proposed_datetime = proposed_dt.isoformat()
    sample_appointment.proposed_by = CreatedBy.CLIENT

    await appointment_scheduler.resync_appointment_jobs(sample_appointment)

    jobs = {job.id: job.next_run_time for job in scheduler.get_jobs()}
    assert set(jobs) == {
        f"appt_{sample_appointment.id}_expire",
        f"appt_{sample_appointment.id}_propose_reminder",
    }
    assert f"appt_{sample_appointment.id}_autoconf" not in jobs
    assert f"appt_{sample_appointment.id}_resch_expire" not in jobs

    expected_expiry = proposed_dt - timedelta(hours=2)
    expected_reminder = proposed_dt - timedelta(hours=3)
    actual_expiry = jobs[f"appt_{sample_appointment.id}_expire"]
    actual_reminder = jobs[f"appt_{sample_appointment.id}_propose_reminder"]
    if actual_expiry.tzinfo:
        expected_expiry = expected_expiry.replace(tzinfo=actual_expiry.tzinfo)
    if actual_reminder.tzinfo:
        expected_reminder = expected_reminder.replace(tzinfo=actual_reminder.tzinfo)
    assert abs((actual_expiry - expected_expiry).total_seconds()) < 1
    assert abs((actual_reminder - expected_reminder).total_seconds()) < 1

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_resync_appointment_jobs_admin_track_multi_round_negotiation_reschedules_timer_each_round(
    appointment_scheduler, scheduler, sample_appointment
):
    """Core scenario this fix targets: simulates 3 rounds of back-and-forth
    negotiation on an admin-invite track (client counters, admin counters
    back, client counters again). At every single round, resync_appointment_jobs
    must cancel the previous round's pending_expiry/propose_reminder pair and
    reschedule a fresh one anchored to the LATEST proposed_datetime -- job ids
    stay stable (no duplicates ever accumulate) while next_run_time advances
    each round, and auto_confirm/reschedule_expiry never appear on this track."""
    scheduler.start()

    sample_appointment.status = AppointmentStatus.PENDING
    sample_appointment.created_by = CreatedBy.ADMIN
    sample_appointment.proposed_datetime = None

    # Round 0: plain unanswered invite, no proposal yet.
    await appointment_scheduler.resync_appointment_jobs(sample_appointment)
    assert {job.id for job in scheduler.get_jobs()} == {f"appt_{sample_appointment.id}_expire"}

    rounds = [
        (_current_tashkent_time() + timedelta(days=3), CreatedBy.CLIENT),
        (_current_tashkent_time() + timedelta(days=6), CreatedBy.ADMIN),
        (_current_tashkent_time() + timedelta(days=9), CreatedBy.CLIENT),
    ]

    previous_run_times = None
    for proposed_dt, proposed_by in rounds:
        sample_appointment.proposed_datetime = proposed_dt.isoformat()
        sample_appointment.proposed_by = proposed_by

        await appointment_scheduler.resync_appointment_jobs(sample_appointment)

        jobs = {job.id: job.next_run_time for job in scheduler.get_jobs()}
        assert set(jobs) == {
            f"appt_{sample_appointment.id}_expire",
            f"appt_{sample_appointment.id}_propose_reminder",
        }
        assert f"appt_{sample_appointment.id}_autoconf" not in jobs
        assert f"appt_{sample_appointment.id}_resch_expire" not in jobs

        expected_expiry = proposed_dt - timedelta(hours=2)
        expected_reminder = proposed_dt - timedelta(hours=3)
        actual_expiry = jobs[f"appt_{sample_appointment.id}_expire"]
        actual_reminder = jobs[f"appt_{sample_appointment.id}_propose_reminder"]
        if actual_expiry.tzinfo:
            expected_expiry = expected_expiry.replace(tzinfo=actual_expiry.tzinfo)
        if actual_reminder.tzinfo:
            expected_reminder = expected_reminder.replace(tzinfo=actual_reminder.tzinfo)
        assert abs((actual_expiry - expected_expiry).total_seconds()) < 1
        assert abs((actual_reminder - expected_reminder).total_seconds()) < 1

        if previous_run_times is not None:
            # Proves the job was actually cancelled and rescheduled this round,
            # not left over untouched from the previous round.
            assert actual_expiry != previous_run_times[0]
            assert actual_reminder != previous_run_times[1]
        previous_run_times = (actual_expiry, actual_reminder)

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_resync_appointment_jobs_noop_without_appointment_id(
    appointment_scheduler, scheduler, sample_appointment
):
    """An appointment without a usable id (None or 0) must be a silent no-op:
    nothing is added or removed from the job store."""
    scheduler.start()

    for missing_id in (None, 0):
        sample_appointment.id = missing_id

        with patch.object(scheduler, "add_job") as mock_add_job, \
             patch.object(scheduler, "remove_job") as mock_remove_job:
            await appointment_scheduler.resync_appointment_jobs(sample_appointment)

            mock_add_job.assert_not_called()
            mock_remove_job.assert_not_called()

    scheduler.shutdown(wait=False)
