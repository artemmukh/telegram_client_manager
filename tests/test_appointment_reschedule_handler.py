"""Handler-level test for submit_reschedule's is_direct_edit branching.

This is a thin, direct-call test: the router is built with fake/mock
collaborators, the decorated `submit_reschedule` callback is pulled out of
`router.callback_query.handlers` (aiogram's callback_query decorator returns
the callback unchanged, see TelegramEventObserver.__call__), and invoked
directly with mock aiogram objects. No dispatcher/polling infrastructure.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.client.appointment_reschedule import create_client_reschedule_router
from bot.keyboards.client.reschedule_cb import ClientRescheduleSubmitCB
from bot.models.appointment import Appointment
from bot.models.user import User
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


def _get_submit_reschedule_handler(router):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == "submit_reschedule":
            return handler.callback
    raise AssertionError("submit_reschedule handler not found on router")


def _client_user():
    return User(full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, telegram_user_id=555, ID=7)


def _appointment(status):
    return Appointment(
        clinic_id=1,
        client_id=7,
        datetime="2026-08-01 10:00",
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=status,
        id=1,
        created_by_telegram_id=999,
    )


def _make_callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = 555
    callback_query.message.edit_text = AsyncMock()
    callback_query.answer = AsyncMock()
    return callback_query


def _make_state():
    state = MagicMock()
    state.get_data = AsyncMock(return_value={"new_datetime": "2026-08-01 10:00", "origin": "manage", "page": 1})
    state.clear = AsyncMock()
    return state


@pytest.mark.asyncio
async def test_submit_reschedule_direct_edit_branch_notifies_and_reschedules_pending_expiry():
    """PENDING result (direct edit): admin gets notify_admin_client_changed_time,
    scheduler resyncs the full job set via resync_appointment_jobs -- and the
    CONFIRMED-branch call (schedule_reschedule_expiry) must NOT fire."""
    resulting_appointment = _appointment(AppointmentStatus.PENDING)

    appointment_management_service = MagicMock()
    appointment_management_service.request_reschedule_by_client = AsyncMock(return_value=resulting_appointment)

    notification_service = MagicMock()
    notification_service.notify_admin_client_changed_time = AsyncMock()
    notification_service.notify_staff_reschedule_requested = AsyncMock()

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()
    appointment_scheduler.schedule_reschedule_expiry = AsyncMock()

    router = create_client_reschedule_router(
        appointment_management_service, notification_service, appointment_scheduler,
    )
    submit_reschedule = _get_submit_reschedule_handler(router)

    await submit_reschedule(
        _make_callback_query(), ClientRescheduleSubmitCB(appointment_id=1), _make_state(), _client_user(),
    )

    notification_service.notify_admin_client_changed_time.assert_awaited_once()
    notification_service.notify_staff_reschedule_requested.assert_not_awaited()

    appointment_scheduler.resync_appointment_jobs.assert_awaited_once_with(resulting_appointment)
    appointment_scheduler.schedule_reschedule_expiry.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_reschedule_negotiation_branch_notifies_staff_and_resyncs_jobs():
    """CONFIRMED result (negotiation): staff gets notify_staff_reschedule_requested,
    scheduler resyncs the full job set via resync_appointment_jobs (both branches call
    it unconditionally as of PR3) -- and the direct-edit-branch notification must NOT
    fire. Proves the is_direct_edit condition still branches on notifications even
    though the job-resync call itself is no longer branched."""
    resulting_appointment = _appointment(AppointmentStatus.CONFIRMED)
    # is_direct_edit is now discriminated by proposed_datetime (PR3), not status --
    # the negotiation branch requires an outstanding proposal to be set.
    resulting_appointment.proposed_datetime = "2026-08-02 10:00"
    resulting_appointment.proposed_by = CreatedBy.CLIENT

    appointment_management_service = MagicMock()
    appointment_management_service.request_reschedule_by_client = AsyncMock(return_value=resulting_appointment)

    notification_service = MagicMock()
    notification_service.notify_admin_client_changed_time = AsyncMock()
    notification_service.notify_staff_reschedule_requested = AsyncMock()

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()
    appointment_scheduler.schedule_reschedule_expiry = AsyncMock()

    router = create_client_reschedule_router(
        appointment_management_service, notification_service, appointment_scheduler,
    )
    submit_reschedule = _get_submit_reschedule_handler(router)

    await submit_reschedule(
        _make_callback_query(), ClientRescheduleSubmitCB(appointment_id=1), _make_state(), _client_user(),
    )

    notification_service.notify_staff_reschedule_requested.assert_awaited_once()
    notification_service.notify_admin_client_changed_time.assert_not_awaited()

    appointment_scheduler.resync_appointment_jobs.assert_awaited_once_with(resulting_appointment)
    appointment_scheduler.schedule_reschedule_expiry.assert_not_awaited()
