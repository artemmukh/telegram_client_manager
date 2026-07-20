"""Tests for the set_status handler's client-notification gate.

CANCELLED must notify the client during normal browsing, but must stay silent
when the status is set from inside the post-appointment editing window
(post_appt=True on the callback data) - see refactoring_record_update.md.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.admin.appointment_management.appointment_browser import (
    create_admin_appointment_browser_router,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import ApptActionCB
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


class FakeAppointmentRepository:
    def __init__(self, appointment):
        self.appointment = appointment
        self.status_updates = []

    async def get_appointment_by_id(self, appointment_id):
        return self.appointment

    async def get_appointments_by_doctor_and_date(self, doctor_id, date):
        return []

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.appointment.status = status
        self.status_updates.append((appointment_id, status))


ADMIN_TELEGRAM_ID = 999


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


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=1, visibility_scope="clinic")


class FakeClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=1, name="Зуб Мудрости", token="t")


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _appointment():
    return Appointment(
        clinic_id=1,
        client_id=1,
        datetime="2026-07-10 10:00",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.CONFIRMED,
        id=1,
    )


def _callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


async def _run_set_status(post_appt: bool, notification_service, appointment_scheduler=None, value="cancelled"):
    appointment_repo = FakeAppointmentRepository(_appointment())
    router = create_admin_appointment_browser_router(
        appointment_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(),
        appointment_scheduler=appointment_scheduler, notification_service=notification_service,
    )
    set_status = _find_handler(router, "set_status")

    callback_data = ApptActionCB(
        action="set_status", appointment_id=1, mode="list", page=1, value=value, post_appt=post_appt,
    )

    await set_status(_callback_query(), callback_data, AsyncMock())


@pytest.mark.asyncio
async def test_set_status_with_invalid_value_shows_alert_and_does_not_update_status():
    """Defensive guard around AppointmentStatus(callback_data.value): a forged/
    malformed status value must short-circuit before any repository/scheduler/
    notification call, answering with a show_alert toast instead of crashing."""
    appointment_repo = FakeAppointmentRepository(_appointment())
    notification_service = AsyncMock()
    appointment_scheduler = AsyncMock()
    router = create_admin_appointment_browser_router(
        appointment_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(),
        appointment_scheduler=appointment_scheduler, notification_service=notification_service,
    )
    set_status = _find_handler(router, "set_status")

    callback_data = ApptActionCB(
        action="set_status", appointment_id=1, mode="list", page=1, value="not-a-real-status", post_appt=False,
    )
    callback_query = _callback_query()

    await set_status(callback_query, callback_data, AsyncMock())

    callback_query.answer.assert_called_once_with("Некорректный статус.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    assert appointment_repo.status_updates == []
    appointment_scheduler.resync_appointment_jobs.assert_not_called()
    notification_service.notify_client_appointment_cancelled_by_admin.assert_not_called()


@pytest.mark.asyncio
async def test_set_status_notifies_client_on_normal_cancellation():
    notification_service = AsyncMock()

    await _run_set_status(post_appt=False, notification_service=notification_service)

    notification_service.notify_client_appointment_cancelled_by_admin.assert_called_once()


@pytest.mark.asyncio
async def test_set_status_does_not_notify_client_on_post_appt_cancellation():
    notification_service = AsyncMock()

    await _run_set_status(post_appt=True, notification_service=notification_service)

    notification_service.notify_client_appointment_cancelled_by_admin.assert_not_called()


# --- Scheduler jobs: set_status resyncs the full job set instead of managing
# individual jobs by hand (see docs on the appointment_browser scheduler migration).


@pytest.mark.asyncio
async def test_set_status_resyncs_jobs_for_terminal_status():
    notification_service = AsyncMock()
    appointment_scheduler = AsyncMock()

    await _run_set_status(
        post_appt=False, notification_service=notification_service,
        appointment_scheduler=appointment_scheduler, value="cancelled",
    )

    appointment_scheduler.resync_appointment_jobs.assert_awaited_once()
    resynced_appointment = appointment_scheduler.resync_appointment_jobs.await_args.args[0]
    assert resynced_appointment.status == AppointmentStatus.CANCELLED

    appointment_scheduler.cancel_appointment_reminders.assert_not_called()
    appointment_scheduler.cancel_auto_confirm.assert_not_called()
    appointment_scheduler.cancel_appointment_completions.assert_not_called()
    appointment_scheduler.cancel_appointment_autocomplete.assert_not_called()
    appointment_scheduler.schedule_appointment_completion.assert_not_called()
    appointment_scheduler.schedule_pending_expiry.assert_not_called()
    appointment_scheduler.schedule_appointment_autocomplete.assert_not_called()


@pytest.mark.asyncio
async def test_set_status_resyncs_jobs_for_confirmed_status():
    notification_service = AsyncMock()
    appointment_scheduler = AsyncMock()

    await _run_set_status(
        post_appt=False, notification_service=notification_service,
        appointment_scheduler=appointment_scheduler, value="confirmed",
    )

    appointment_scheduler.resync_appointment_jobs.assert_awaited_once()
    resynced_appointment = appointment_scheduler.resync_appointment_jobs.await_args.args[0]
    assert resynced_appointment.status == AppointmentStatus.CONFIRMED

    appointment_scheduler.cancel_appointment_reminders.assert_not_called()
    appointment_scheduler.cancel_auto_confirm.assert_not_called()
    appointment_scheduler.cancel_appointment_completions.assert_not_called()
    appointment_scheduler.cancel_appointment_autocomplete.assert_not_called()
    appointment_scheduler.schedule_appointment_completion.assert_not_called()
    appointment_scheduler.schedule_pending_expiry.assert_not_called()
    appointment_scheduler.schedule_appointment_autocomplete.assert_not_called()
