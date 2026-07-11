"""Tests for AppointmentScheduler service."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.models.appointment import Appointment
from bot.models.user import User
from bot.services.appointment.appointment_jobs import (
    expire_pending_request_job,
    expire_reschedule_request_job,
)
from bot.services.appointment.appointment_scheduler import (
    AppointmentScheduler,
    _current_tashkent_time,
)
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


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
def mock_notification_service():
    """Mock AppointmentNotificationService."""
    service = AsyncMock()
    service.notify_client_reminder_without_buttons = AsyncMock(return_value=True)
    service.notify_client_reminder_with_buttons = AsyncMock(return_value=True)
    service.notify_admin_upcoming_appointment = AsyncMock()
    return service


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
    scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service
):
    """Create AppointmentScheduler instance."""
    return AppointmentScheduler(
        scheduler=scheduler,
        appointment_repo=mock_appointment_repo,
        user_repo=mock_user_repo,
        notification_service=mock_notification_service,
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
    # Setup appointment with admin telegram ID
    sample_appointment.created_by_telegram_id = 12345
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment
    mock_user_repo.get_client_by_id.return_value = MagicMock(full_name="Test Client")

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


# Reminder preference filtering (Phase 3b + Fix 3 admin preferences)
#
# Since Fix 3, schedule_appointment_reminders() ORs the client's and the
# admin's per-slot preference (a slot is scheduled if EITHER wants it), so
# every test below pins BOTH get_client_by_id and get_user_by_telegram_id
# explicitly. Tests that mean to isolate "client preference" pin the admin
# to opted-out (False, False) so the admin can't accidentally supply the
# result being asserted.


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
async def test_reminders_respect_24h_only_preference(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """Client who opted out of the 2h reminder only gets the 24h job scheduled,
    given an admin who independently wants nothing (isolates client preference)."""
    scheduler.start()
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(True, False)
    mock_user_repo.get_user_by_telegram_id.return_value = _admin_with_preferences(False, False)

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {f"appt_{sample_appointment.id}_24h"}

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_reminders_respect_2h_only_preference(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """Client who opted out of the 24h reminder only gets the 2h job scheduled,
    given an admin who independently wants nothing (isolates client preference)."""
    scheduler.start()
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(False, True)
    mock_user_repo.get_user_by_telegram_id.return_value = _admin_with_preferences(False, False)

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {f"appt_{sample_appointment.id}_2h"}

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_reminders_respect_both_disabled_preference(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """Client and admin who both opted out of everything get no reminder jobs
    scheduled at all."""
    scheduler.start()
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(False, False)
    mock_user_repo.get_user_by_telegram_id.return_value = _admin_with_preferences(False, False)

    await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    assert scheduler.get_jobs() == []

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
# schedule_appointment_reminders() now schedules a slot if the CLIENT OR the
# ADMIN wants it, and threads both flags into the job's args so the firing
# job knows who to notify.


@pytest.mark.asyncio
async def test_admin_only_wanting_24h_slot_still_schedules_job(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """Client opted out of the 24h reminder, but the admin wants it -> the 24h
    job IS scheduled (OR semantics) and carries the correct per-party flags."""
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
        sample_appointment.id, 24, False, True,
    )

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_admin_only_wanting_2h_slot_still_schedules_job(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """Admin opted out of the 2h reminder, but the client wants it -> the 2h
    job IS scheduled and carries the correct per-party flags."""
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
        sample_appointment.id, 2, True, False,
    )

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_neither_client_nor_admin_wanting_2h_slot_skips_add_job(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """When neither party wants a given slot, add_job must never be invoked for
    it (stronger guarantee than just "absent from the final job list")."""
    scheduler.start()
    mock_user_repo.get_client_by_id.return_value = _client_with_preferences(True, False)
    mock_user_repo.get_user_by_telegram_id.return_value = _admin_with_preferences(True, False)

    with patch.object(scheduler, "add_job") as mock_add_job:
        await appointment_scheduler.schedule_appointment_reminders(sample_appointment)

    scheduled_ids = {call.kwargs.get("id") for call in mock_add_job.call_args_list}
    assert scheduled_ids == {f"appt_{sample_appointment.id}_24h"}

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_admin_unresolved_defaults_to_wanting_slot(
    appointment_scheduler, scheduler, mock_user_repo, sample_appointment
):
    """When the admin can't be resolved (get_user_by_telegram_id -> None), the
    admin defaults to wanting the reminder (True), matching pre-fix
    unconditional-send behavior for the unresolvable case. Client is pinned
    opted-out so the scheduled jobs here are fully explained by the admin
    default."""
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
        sample_appointment.id, 24, False, True,
    )
    assert jobs[f"appt_{sample_appointment.id}_2h"].args == (
        sample_appointment.id, 2, False, True,
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


# Fix 3: admin reminder preferences - job firing half
#
# send_reminder_job() receives notify_client/notify_admin captured at
# schedule time and must gate each party's send independently. This is the
# exact regression the fix guards against: once admin-only-wanted jobs can
# exist, an unguarded client-send would mean a client who disabled reminders
# starts receiving them again.


@pytest.mark.asyncio
async def test_fired_reminder_suppresses_client_when_only_admin_wants_24h_slot(
    appointment_scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Client reminder_24h=False, admin reminder_24h=True: the 24h job was
    scheduled for the admin's sake only. When fired with
    notify_client=False, notify_admin=True, the CLIENT message must NOT be
    sent while the ADMIN message IS sent."""
    sample_appointment.created_by_telegram_id = 12345
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment
    mock_user_repo.get_client_by_id.return_value = MagicMock(full_name="Test Client")

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
                sample_appointment.id, hours_before=24, notify_client=False, notify_admin=True,
            )

            mock_notification_service.notify_client_reminder_without_buttons.assert_not_called()
            mock_notification_service.notify_client_reminder_with_buttons.assert_not_called()
            mock_notification_service.notify_admin_upcoming_appointment.assert_called_once_with(
                sample_appointment.created_by_telegram_id, sample_appointment, "Test Client",
            )


@pytest.mark.asyncio
async def test_fired_reminder_suppresses_admin_when_only_client_wants_2h_slot(
    appointment_scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Mirror case: admin reminder_2h=False, client reminder_2h=True. When
    fired with notify_client=True, notify_admin=False, the ADMIN message must
    NOT be sent while the CLIENT message IS sent."""
    sample_appointment.created_by_telegram_id = 12345
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment
    mock_user_repo.get_client_by_id.return_value = MagicMock(full_name="Test Client")

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
                sample_appointment.id, hours_before=2, notify_client=True, notify_admin=False,
            )

            mock_notification_service.notify_client_reminder_with_buttons.assert_called_once_with(
                sample_appointment
            )
            mock_notification_service.notify_admin_upcoming_appointment.assert_not_called()


@pytest.mark.asyncio
async def test_fired_reminder_sends_to_both_when_both_want_slot(
    appointment_scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Both client and admin want a slot -> both messages sent (existing
    behavior, must not regress)."""
    sample_appointment.created_by_telegram_id = 12345
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment
    mock_user_repo.get_client_by_id.return_value = MagicMock(full_name="Test Client")

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
                sample_appointment.id, hours_before=2, notify_client=True, notify_admin=True,
            )

            mock_notification_service.notify_client_reminder_with_buttons.assert_called_once_with(
                sample_appointment
            )
            mock_notification_service.notify_admin_upcoming_appointment.assert_called_once_with(
                sample_appointment.created_by_telegram_id, sample_appointment, "Test Client",
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
async def test_mark_appointment_completed_job_updates_status_if_pending(
    appointment_scheduler, mock_appointment_repo, sample_appointment
):
    """Test that completion job updates status to COMPLETED if appointment is PENDING."""
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
            mock_user_repo_class.return_value = AsyncMock()
            mock_notif_class.return_value = AsyncMock()

            await appointment_scheduler._mark_appointment_completed_job(sample_appointment.id)

            mock_appointment_repo.update_appointment_status.assert_called_once_with(
                sample_appointment.id,
                AppointmentStatus.COMPLETED,
                ANY,
            )


@pytest.mark.asyncio
async def test_mark_appointment_completed_job_updates_status_if_confirmed(
    appointment_scheduler, mock_appointment_repo, sample_appointment
):
    """Test that completion job updates status to COMPLETED if appointment is CONFIRMED."""
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
            mock_user_repo_class.return_value = AsyncMock()
            mock_notif_class.return_value = AsyncMock()

            await appointment_scheduler._mark_appointment_completed_job(confirmed_appointment.id)

            mock_appointment_repo.update_appointment_status.assert_called_once_with(
                confirmed_appointment.id,
                AppointmentStatus.COMPLETED,
                ANY,
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
    """Test that pending expiry runs at the appointment's requested datetime."""
    scheduler.start()

    expected_expiry_time = datetime.fromisoformat(sample_appointment.datetime)

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
async def test_expire_pending_request_job_skips_if_not_client_created(
    mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Test that the expiry job skips a PENDING request that was created by an admin
    (only client self-booking requests can expire)."""
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

            mock_appointment_repo.update_appointment_status.assert_not_called()
            mock_notification_service.notify_client_pending_request_expired.assert_not_called()


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
async def test_expire_reschedule_request_job_skips_if_not_confirmed(
    mock_appointment_repo, mock_user_repo, mock_notification_service, sample_reschedule_appointment
):
    """Test that the expiry job skips an appointment that is no longer CONFIRMED
    (e.g. it was already cancelled)."""
    sample_reschedule_appointment.status = AppointmentStatus.CANCELLED
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
async def test_expire_reschedule_request_job_skips_if_proposed_by_not_client(
    mock_appointment_repo, mock_user_repo, mock_notification_service, sample_reschedule_appointment
):
    """Test that the expiry job skips an admin-proposed counter-offer (2b behavior) -
    only client-initiated reschedule requests expire via this job."""
    sample_reschedule_appointment.proposed_by = CreatedBy.ADMIN
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
