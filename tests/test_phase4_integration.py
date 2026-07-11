"""Integration tests for Phase 4: Auto-Complete Workflow.

Tests the complete workflow of appointment auto-completion:
- Create appointment → completion scheduled
- Update datetime → completion rescheduled
- Cancel appointment → completion cancelled
- Delete appointment → completion cancelled
- Status changes → completion correctly handled
- Full workflow → create → confirm → auto-complete after 1h
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.models.appointment import Appointment
from bot.models.user import User
from bot.services.appointment.appointment_scheduler import AppointmentScheduler
from bot.services.appointment.appointment_management import AppointmentManagement
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
def mock_staff_repo():
    """Mock StaffRepository."""
    repo = AsyncMock()
    return repo


@pytest.fixture
def mock_clinic_repo():
    """Mock ClinicRepository."""
    repo = AsyncMock()
    return repo


@pytest.fixture
def mock_notification_service():
    """Mock AppointmentNotificationService."""
    service = AsyncMock()
    service.notify_client_appointment = AsyncMock(return_value=True)
    service.bot = AsyncMock()
    service.bot.send_message = AsyncMock()
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


# Phase 4 Integration Tests


@pytest.mark.asyncio
async def test_create_appointment_schedules_completion(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test: Create appointment → completion scheduled."""
    scheduler.start()

    await appointment_scheduler.schedule_appointment_completion(sample_appointment)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == f"appt_{sample_appointment.id}_complete"

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_update_datetime_reschedules_completion(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test: Update datetime → completion rescheduled."""
    scheduler.start()

    # Schedule initial completion
    await appointment_scheduler.schedule_appointment_completion(sample_appointment)
    assert len(scheduler.get_jobs()) == 1

    # Simulate datetime update
    new_datetime = datetime.fromisoformat(sample_appointment.datetime) + timedelta(hours=3)
    sample_appointment.datetime = new_datetime.isoformat()

    # Reschedule completion
    await appointment_scheduler.cancel_appointment_completions(sample_appointment.id)
    await appointment_scheduler.schedule_appointment_completion(sample_appointment)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == f"appt_{sample_appointment.id}_complete"

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_appointment_cancels_completion(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test: Cancel appointment → completion cancelled."""
    scheduler.start()

    # Schedule completion
    await appointment_scheduler.schedule_appointment_completion(sample_appointment)
    assert len(scheduler.get_jobs()) == 1

    # Cancel completion
    await appointment_scheduler.cancel_appointment_completions(sample_appointment.id)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_delete_appointment_cancels_completion(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test: Delete appointment → completion cancelled."""
    scheduler.start()

    # Schedule completion
    await appointment_scheduler.schedule_appointment_completion(sample_appointment)
    assert len(scheduler.get_jobs()) == 1

    # Cancel completion (as if appointment is deleted)
    await appointment_scheduler.cancel_appointment_completions(sample_appointment.id)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_status_change_to_cancelled_cancels_completion(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test: Status changed to CANCELLED → completion cancelled."""
    scheduler.start()

    # Schedule completion for PENDING appointment
    await appointment_scheduler.schedule_appointment_completion(sample_appointment)
    assert len(scheduler.get_jobs()) == 1

    # Change status to CANCELLED
    sample_appointment.status = AppointmentStatus.CANCELLED
    await appointment_scheduler.cancel_appointment_completions(sample_appointment.id)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_status_change_to_no_show_cancels_completion(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test: Status changed to NO_SHOW → completion cancelled."""
    scheduler.start()

    # Schedule completion for PENDING appointment
    await appointment_scheduler.schedule_appointment_completion(sample_appointment)
    assert len(scheduler.get_jobs()) == 1

    # Change status to NO_SHOW
    sample_appointment.status = AppointmentStatus.NO_SHOW
    await appointment_scheduler.cancel_appointment_completions(sample_appointment.id)

    assert len(scheduler.get_jobs()) == 0

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_status_change_back_to_confirmed_reschedules_completion(
    appointment_scheduler, scheduler, sample_appointment
):
    """Test: Status changed from CANCELLED back to CONFIRMED → completion rescheduled."""
    scheduler.start()

    # First schedule completion
    await appointment_scheduler.schedule_appointment_completion(sample_appointment)
    assert len(scheduler.get_jobs()) == 1

    # Change to CANCELLED and cancel completion
    await appointment_scheduler.cancel_appointment_completions(sample_appointment.id)
    assert len(scheduler.get_jobs()) == 0

    # Change back to CONFIRMED and reschedule completion
    sample_appointment.status = AppointmentStatus.CONFIRMED
    await appointment_scheduler.schedule_appointment_completion(sample_appointment)

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == f"appt_{sample_appointment.id}_complete"

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_completion_job_updates_pending_to_completed(
    appointment_scheduler, mock_appointment_repo, mock_user_repo, sample_appointment
):
    """Test: Completion job changes PENDING status to COMPLETED."""
    # Mock the fetch of appointment data
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment

    # Run completion job
    await appointment_scheduler._mark_appointment_completed_job(sample_appointment.id)

    # Verify status update was called
    mock_appointment_repo.update_appointment_status.assert_called_once_with(
        sample_appointment.id,
        AppointmentStatus.COMPLETED
    )


@pytest.mark.asyncio
async def test_completion_job_updates_confirmed_to_completed(
    appointment_scheduler, mock_appointment_repo, mock_user_repo, sample_appointment
):
    """Test: Completion job changes CONFIRMED status to COMPLETED."""
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

    await appointment_scheduler._mark_appointment_completed_job(confirmed_appointment.id)

    mock_appointment_repo.update_appointment_status.assert_called_once_with(
        confirmed_appointment.id,
        AppointmentStatus.COMPLETED
    )


@pytest.mark.asyncio
async def test_completion_job_skips_already_cancelled(
    appointment_scheduler, mock_appointment_repo, sample_appointment
):
    """Test: Completion job skips already CANCELLED appointment."""
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

    await appointment_scheduler._mark_appointment_completed_job(cancelled_appointment.id)

    # Verify update was NOT called
    mock_appointment_repo.update_appointment_status.assert_not_called()


@pytest.mark.asyncio
async def test_completion_job_skips_already_no_show(
    appointment_scheduler, mock_appointment_repo, sample_appointment
):
    """Test: Completion job skips already NO_SHOW appointment."""
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

    await appointment_scheduler._mark_appointment_completed_job(no_show_appointment.id)

    # Verify update was NOT called
    mock_appointment_repo.update_appointment_status.assert_not_called()


@pytest.mark.asyncio
async def test_completion_job_skips_already_completed(
    appointment_scheduler, mock_appointment_repo, sample_appointment
):
    """Test: Completion job skips already COMPLETED appointment."""
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

    await appointment_scheduler._mark_appointment_completed_job(completed_appointment.id)

    # Verify update was NOT called
    mock_appointment_repo.update_appointment_status.assert_not_called()


@pytest.mark.asyncio
async def test_completion_job_notifies_admin_not_client(
    appointment_scheduler, mock_appointment_repo, mock_notification_service, sample_appointment
):
    """Test: Completion job notifies the admin who created the appointment, never the client."""
    sample_appointment.created_by_telegram_id = 54321

    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment

    await appointment_scheduler._mark_appointment_completed_job(sample_appointment.id)

    mock_notification_service.notify_admin_completion.assert_called_once_with(
        54321, sample_appointment
    )
    mock_notification_service.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_completion_job_skips_admin_notification_when_no_creator(
    appointment_scheduler, mock_appointment_repo, mock_notification_service, sample_appointment
):
    """Test: Completion job does not attempt an admin notification when created_by_telegram_id is unset."""
    sample_appointment.created_by_telegram_id = None

    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment

    # Should not raise error
    await appointment_scheduler._mark_appointment_completed_job(sample_appointment.id)

    # Status update should still happen
    mock_appointment_repo.update_appointment_status.assert_called_once()
    mock_notification_service.notify_admin_completion.assert_not_called()


@pytest.mark.asyncio
async def test_completion_job_swallows_admin_notification_failure(
    appointment_scheduler, mock_appointment_repo, mock_notification_service, sample_appointment
):
    """Test: A failed admin completion notification must not crash the job; status update already committed."""
    sample_appointment.created_by_telegram_id = 54321
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment
    mock_notification_service.notify_admin_completion.side_effect = Exception("boom")

    # Should not raise error
    await appointment_scheduler._mark_appointment_completed_job(sample_appointment.id)

    mock_appointment_repo.update_appointment_status.assert_called_once_with(
        sample_appointment.id,
        AppointmentStatus.COMPLETED
    )


@pytest.mark.asyncio
async def test_full_workflow_pending_to_completed(
    appointment_scheduler, scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Test: Full workflow - create → stay PENDING → auto-complete after 1h → admin follow-up notified."""
    scheduler.start()

    sample_appointment.created_by_telegram_id = 54321

    # 1. Create appointment (initially PENDING)
    await appointment_scheduler.schedule_appointment_completion(sample_appointment)
    assert len(scheduler.get_jobs()) == 1

    # 2. Setup mock for completion job
    mock_appointment_repo.get_appointment_by_id.return_value = sample_appointment

    # 3. Run completion job (simulating time passing)
    await appointment_scheduler._mark_appointment_completed_job(sample_appointment.id)

    # 4. Verify status was updated to COMPLETED
    mock_appointment_repo.update_appointment_status.assert_called_once_with(
        sample_appointment.id,
        AppointmentStatus.COMPLETED
    )

    # 5. Verify the admin (not the client) was notified about the completion follow-up
    mock_notification_service.notify_admin_completion.assert_called_once_with(
        54321, sample_appointment
    )
    mock_notification_service.bot.send_message.assert_not_called()

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_full_workflow_confirmed_to_completed(
    appointment_scheduler, scheduler, mock_appointment_repo, mock_user_repo, mock_notification_service, sample_appointment
):
    """Test: Full workflow - create → client confirms → auto-complete after 1h."""
    scheduler.start()

    # 1. Create appointment (initially PENDING)
    await appointment_scheduler.schedule_appointment_completion(sample_appointment)
    assert len(scheduler.get_jobs()) == 1

    # 2. Client confirms (status changes to CONFIRMED)
    confirmed_appointment = Appointment(
        id=sample_appointment.id,
        clinic_id=sample_appointment.clinic_id,
        client_id=sample_appointment.client_id,
        datetime=sample_appointment.datetime,
        purpose=sample_appointment.purpose,
        created_by=sample_appointment.created_by,
        status=AppointmentStatus.CONFIRMED,
        clinic_name=sample_appointment.clinic_name,
    )

    # 3. Setup mock for completion job
    mock_appointment_repo.get_appointment_by_id.return_value = confirmed_appointment
    mock_user_repo.get_client_by_id.return_value = User(
        ID=1,
        phone="+998901234567",
        full_name="Test Client",
        role=Role.CLIENT,
        telegram_user_id=123456,
    )

    # 4. Run completion job (simulating time passing after appointment)
    await appointment_scheduler._mark_appointment_completed_job(sample_appointment.id)

    # 5. Verify status was updated to COMPLETED
    mock_appointment_repo.update_appointment_status.assert_called_once_with(
        sample_appointment.id,
        AppointmentStatus.COMPLETED
    )

    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_multiple_appointments_independent_lifecycle(
    appointment_scheduler, scheduler, mock_appointment_repo, mock_user_repo, sample_appointment
):
    """Test: Multiple appointments have independent completion lifecycles."""
    scheduler.start()

    # Create two appointments
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

    # Schedule both
    await appointment_scheduler.schedule_appointment_completion(appt1)
    await appointment_scheduler.schedule_appointment_completion(appt2)
    assert len(scheduler.get_jobs()) == 2

    # Cancel appt1 completion
    await appointment_scheduler.cancel_appointment_completions(1)

    # Verify only appt2 remains
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "appt_2_complete"

    # Complete appt2
    mock_appointment_repo.get_appointment_by_id.return_value = appt2
    mock_user_repo.get_client_by_id.return_value = None
    await appointment_scheduler._mark_appointment_completed_job(2)

    # Verify appt2 status was updated
    mock_appointment_repo.update_appointment_status.assert_called_with(
        2,
        AppointmentStatus.COMPLETED
    )

    scheduler.shutdown(wait=False)
