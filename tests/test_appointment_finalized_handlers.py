"""Regression tests for stale admin keyboards on finalized appointments."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.admin.appointment_management.booking_requests import (
    create_admin_booking_requests_router,
)
from bot.handlers.admin.appointment_management.reschedule_requests import (
    create_admin_reschedule_requests_router,
)
from bot.keyboards.admin.record_management_kb.booking_request_cb import (
    BookingRequestActionCB,
)
from bot.keyboards.admin.record_management_kb.reschedule_request_cb import (
    RescheduleRequestActionCB,
)
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role

ADMIN_TELEGRAM_ID = 999


class _AppointmentRepository:
    def __init__(self, appointment):
        self.appointment = appointment

    async def get_appointment_by_id(self, appointment_id):
        return self.appointment


class _UserRepository:
    async def get_user_by_telegram_id(self, telegram_user_id):
        return _admin_user() if telegram_user_id == ADMIN_TELEGRAM_ID else None


class _StaffRepository:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=1, visibility_scope="clinic")


class _ClinicRepository:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=1, name="Clinic", token="token")


def _admin_user():
    return User(
        full_name="Petrov Petr", phone="+998907654321", role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID, ID=1, clinic_id=1, clinic_name="Clinic",
    )


def _appointment(status=AppointmentStatus.CANCELLED):
    return Appointment(
        clinic_id=1, client_id=7, doctor_id=5, datetime="2026-08-01 10:00",
        purpose="Konsultatsiya", created_by=CreatedBy.CLIENT, status=status, id=1,
    )


def _callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.chat.id = 555
    callback_query.message.message_id = 777
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _repositories(appointment):
    return (
        _AppointmentRepository(appointment),
        _UserRepository(),
        _StaffRepository(),
        _ClinicRepository(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["confirm", "reject"])
async def test_finalized_booking_request_invalidates_own_message(action):
    repository_args = _repositories(_appointment())
    router = create_admin_booking_requests_router("zb", *repository_args)
    handler = next(
        item.callback for item in router.callback_query.handlers
        if item.callback.__name__ == ("confirm_request" if action == "confirm" else "reject_request")
    )
    callback_query = _callback_query()

    await handler(
        callback_query,
        BookingRequestActionCB(action=action, appointment_id=1),
        _admin_user(),
    )

    callback_query.answer.assert_awaited_once_with("Эта заявка больше недоступна.", show_alert=True)
    callback_query.message.edit_text.assert_awaited_once_with(
        "⛔️ Заявка больше не актуальна.", reply_markup=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["accept", "reject"])
async def test_finalized_reschedule_request_invalidates_own_message(action):
    repository_args = _repositories(_appointment())
    router = create_admin_reschedule_requests_router("zb", *repository_args)
    handler_name = "accept_reschedule" if action == "accept" else "reject_reschedule"
    handler = next(item.callback for item in router.callback_query.handlers if item.callback.__name__ == handler_name)
    callback_query = _callback_query()

    await handler(
        callback_query,
        RescheduleRequestActionCB(action=action, appointment_id=1),
        _admin_user(),
    )

    callback_query.answer.assert_awaited_once_with("Эта запись больше недоступна.", show_alert=True)
    callback_query.message.edit_text.assert_awaited_once_with(
        "⛔️ Запись больше не актуальна.", reply_markup=None,
    )


@pytest.mark.asyncio
async def test_finalized_message_edit_failure_does_not_escape_handler():
    repository_args = _repositories(_appointment())
    router = create_admin_booking_requests_router("zb", *repository_args)
    handler = next(item.callback for item in router.callback_query.handlers if item.callback.__name__ == "confirm_request")
    callback_query = _callback_query()
    callback_query.message.edit_text.side_effect = RuntimeError("message is not modified")

    await handler(
        callback_query,
        BookingRequestActionCB(action="confirm", appointment_id=1),
        _admin_user(),
    )

    callback_query.answer.assert_awaited_once_with("Эта заявка больше недоступна.", show_alert=True)


@pytest.mark.asyncio
async def test_finalized_booking_proposal_clears_message_and_state():
    repository_args = _repositories(_appointment())
    router = create_admin_booking_requests_router("zb", *repository_args)
    handler = next(
        item.callback for item in router.callback_query.handlers
        if item.callback.__name__ == "approve_propose_datetime"
    )
    callback_query = _callback_query()
    state = MagicMock()
    state.get_data = AsyncMock(return_value={
        "appointment_datetime_parsed": datetime(2030, 1, 1, 12, 0),
        "appointment_datetime_display": "01.01.2030 12:00",
    })
    state.clear = AsyncMock()

    await handler(
        callback_query,
        BookingRequestActionCB(action="approve_propose_datetime", appointment_id=1),
        state,
        _admin_user(),
    )

    callback_query.message.edit_text.assert_awaited_once_with(
        "⛔️ Заявка больше не актуальна.", reply_markup=None,
    )
    state.clear.assert_awaited_once()
