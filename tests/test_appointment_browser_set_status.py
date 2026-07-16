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
            visibility_scope="clinic",
        )


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=1)


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


async def _run_set_status(post_appt: bool, notification_service):
    appointment_repo = FakeAppointmentRepository(_appointment())
    router = create_admin_appointment_browser_router(
        appointment_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(),
        appointment_scheduler=None, notification_service=notification_service,
    )
    set_status = _find_handler(router, "set_status")

    callback_data = ApptActionCB(
        action="set_status", appointment_id=1, mode="list", page=1, value="cancelled", post_appt=post_appt,
    )

    await set_status(_callback_query(), callback_data, AsyncMock())


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
