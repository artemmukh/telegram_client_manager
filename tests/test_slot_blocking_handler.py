"""Handler-level tests for the admin slot-blocking router
(bot/handlers/admin/appointment_management/slot_blocking.py), focused on
confirm_block_creation: the branch that turns a rejected create_block() into a
redrawn blocking menu instead of leaving the admin stranded on a dead
confirmation screen.

Follows the direct-handler-call/fake-repository convention established in
tests/test_booking_requests_calendar_slot_picker.py.
"""
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.admin.appointment_management.slot_blocking import (
    create_admin_slot_blocking_router,
)
from bot.keyboards.admin.record_management_kb.appointment_kb import back_to_records_kb
from bot.keyboards.admin.record_management_kb.slot_blocking_cb import SlotBlockConfirmCB
from bot.keyboards.admin.record_management_kb.slot_blocking_kb import slot_blocking_menu_kb
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.services.utils.date_parser import get_current_tashkent_datetime
from bot.utils.role import Role
from tests.conftest import FakeBlockedSlotRepository

ADMIN_TELEGRAM_ID = 999
CLINIC_ID = 1
DOCTOR_ID = 42

_MENU_TEXT = "🚫 Блокировка слотов"
_BLOCK_CREATED_TEXT = "✅ Блокировка создана."


class FakeAppointmentRepository:
    def __init__(self, appointments=None):
        self.appointments = list(appointments or [])
        self.status_updates = []

    async def get_appointments_in_range(self, clinic_id, doctor_id, start_datetime, end_datetime):
        return [
            a for a in self.appointments
            if a.clinic_id == clinic_id
            and (doctor_id is None or a.doctor_id == doctor_id)
            and start_datetime <= a.datetime < end_datetime
        ]

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.status_updates.append((appointment_id, status))


class FakeUserRepo:
    def __init__(self, admin=None):
        self.admin = admin

    async def get_user_by_telegram_id(self, telegram_user_id):
        if self.admin is not None and self.admin.telegram_user_id == telegram_user_id:
            return self.admin
        return None

    async def get_user_by_id(self, user_id):
        if self.admin is not None and self.admin.ID == user_id:
            return self.admin
        return None

    async def get_staff_users_by_clinic_id(self, clinic_id):
        return [self.admin] if self.admin is not None else []


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=CLINIC_ID, visibility_scope="clinic")

    async def get_staff_by_clinic_id(self, clinic_id):
        return [await self.get_staff(ADMIN_TELEGRAM_ID)]


class FakeClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=CLINIC_ID, name="Зуб Мудрости", token="t")


def _admin_user():
    return User(
        full_name="Петров Петр", phone="+998907654321", role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID, ID=DOCTOR_ID, clinic_id=CLINIC_ID, clinic_name="Зуб Мудрости",
    )


def _build_router(blocked_slot_repo=None, appt_repo=None):
    return create_admin_slot_blocking_router(
        FakeUserRepo(_admin_user()),
        FakeStaffRepo(),
        FakeClinicRepo(),
        appt_repo if appt_repo is not None else FakeAppointmentRepository(),
        blocked_slot_repo if blocked_slot_repo is not None else FakeBlockedSlotRepository(),
    )


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _state(**data):
    state = MagicMock()
    state.get_data = AsyncMock(return_value=data)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


def _raw_range(offset_days, hour=10, duration_hours=1):
    start_dt = get_current_tashkent_datetime().replace(
        hour=hour, minute=0, second=0, microsecond=0,
    ) + timedelta(days=offset_days)
    end_dt = start_dt + timedelta(hours=duration_hours)
    return start_dt.strftime("%d.%m.%Y %H:%M"), end_dt.strftime("%d.%m.%Y %H:%M")


# --- confirm_block_creation ---

@pytest.mark.asyncio
async def test_confirm_block_creation_redraws_the_blocking_menu_when_the_service_rejects_the_block():
    """A fully past range makes create_block raise InvalidBlockRangeError. The
    admin must land back on the blocking menu with a cleared state, not on a
    stale confirmation screen whose buttons no longer do anything."""
    blocked_slot_repo = FakeBlockedSlotRepository()
    router = _build_router(blocked_slot_repo)
    confirm_block_creation = _find_handler(router, "confirm_block_creation")

    start_raw, end_raw = _raw_range(offset_days=-1)
    callback_query = _callback_query()
    state = _state(
        clinic_id=CLINIC_ID, staff_id=DOCTOR_ID,
        range_start_raw=start_raw, range_end_raw=end_raw,
        range_start="", range_end="", reason="Отпуск",
    )

    await confirm_block_creation(
        callback_query, SlotBlockConfirmCB(action="create"), state, _admin_user(),
    )

    assert blocked_slot_repo.blocks == []
    state.clear.assert_awaited_once()
    callback_query.answer.assert_awaited_once_with(
        "Нельзя заблокировать полностью прошедший интервал.", show_alert=True,
    )
    callback_query.message.edit_text.assert_awaited_once_with(
        _MENU_TEXT, reply_markup=slot_blocking_menu_kb(lang="ru"),
    )


@pytest.mark.asyncio
async def test_confirm_block_creation_reports_success_on_a_valid_range():
    """Contrast case for the rejection test above: a valid range must NOT land
    on the blocking menu."""
    blocked_slot_repo = FakeBlockedSlotRepository()
    router = _build_router(blocked_slot_repo)
    confirm_block_creation = _find_handler(router, "confirm_block_creation")

    start_raw, end_raw = _raw_range(offset_days=2)
    callback_query = _callback_query()
    state = _state(
        clinic_id=CLINIC_ID, staff_id=DOCTOR_ID,
        range_start_raw=start_raw, range_end_raw=end_raw,
        range_start="", range_end="", reason="Отпуск",
    )

    await confirm_block_creation(
        callback_query, SlotBlockConfirmCB(action="create"), state, _admin_user(),
    )

    assert len(blocked_slot_repo.blocks) == 1
    assert blocked_slot_repo.blocks[0].reason == "Отпуск"
    callback_query.message.edit_text.assert_awaited_once_with(
        _BLOCK_CREATED_TEXT, reply_markup=back_to_records_kb(lang="ru"),
    )
    state.clear.assert_awaited_once()
