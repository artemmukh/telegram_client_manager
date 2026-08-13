"""Tests for the post-appointment status-selection flow in appointment_browser.py.

Three handlers cooperate here:
- open_status_menu: renders appointment_status_menu_kb for a terminal-status
  appointment (COMPLETED/NO_SHOW/CANCELLED), offering the other 2 statuses.
- select_status: a pure re-render of the post-appt card marking whichever
  status the admin is currently considering -- never touches the repository
  or the scheduler.
- finish_appointment: commits whichever status was actually selected (falling
  back to COMPLETED when no value was carried), then resyncs scheduler jobs.
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


ADMIN_TELEGRAM_ID = 999


class FakeAppointmentRepository:
    def __init__(self, appointment):
        self.appointment = appointment
        self.status_updates = []

    async def get_appointment_by_id(self, appointment_id):
        return self.appointment

    async def get_appointments_by_doctor_and_date(self, doctor_id, date):
        return []

    async def get_appointment_notification(self, appointment_id, chat_id, message_id, kind):
        return None

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.appointment.status = status
        self.status_updates.append((appointment_id, status))


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


def _admin_user():
    return User(
        full_name="Петров Петр",
        phone="+998907654321",
        role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID,
        ID=1,
        clinic_id=1,
        clinic_name="Зуб Мудрости",
    )


def _appointment(status=AppointmentStatus.CONFIRMED):
    return Appointment(
        clinic_id=1,
        client_id=1,
        datetime="2026-07-10 10:00",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=status,
        id=1,
    )


def _callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _router(appointment_repo, appointment_scheduler=None, notification_service=None):
    return create_admin_appointment_browser_router(
        "zb", appointment_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(),
        appointment_scheduler=appointment_scheduler, notification_service=notification_service,
    )


# --- select_status: pure re-render, no writes ---

@pytest.mark.asyncio
async def test_select_status_rerenders_card_with_selected_status_marked():
    appointment_repo = FakeAppointmentRepository(_appointment())
    router = _router(appointment_repo)
    select_status = _find_handler(router, "select_status")

    callback_query = _callback_query()
    callback_data = ApptActionCB(
        action="select_status", appointment_id=1, mode="list", page=1, value="no_show", post_appt=True,
    )

    await select_status(callback_query, callback_data, AsyncMock(), _admin_user())

    reply_markup = callback_query.message.edit_text.call_args.kwargs["reply_markup"]
    buttons = [button for row in reply_markup.inline_keyboard for button in row]
    marked = [b for b in buttons if b.text.startswith("☑️")]

    assert len(marked) == 1
    assert ApptActionCB.unpack(marked[0].callback_data).value == "no_show"


@pytest.mark.asyncio
async def test_select_status_does_not_write_to_repository_or_scheduler():
    appointment_repo = FakeAppointmentRepository(_appointment())
    appointment_scheduler = AsyncMock()
    router = _router(appointment_repo, appointment_scheduler=appointment_scheduler)
    select_status = _find_handler(router, "select_status")

    callback_query = _callback_query()
    callback_data = ApptActionCB(
        action="select_status", appointment_id=1, mode="list", page=1, value="cancelled", post_appt=True,
    )

    await select_status(callback_query, callback_data, AsyncMock(), _admin_user())

    assert appointment_repo.status_updates == []
    assert appointment_repo.appointment.status is AppointmentStatus.CONFIRMED
    appointment_scheduler.resync_appointment_jobs.assert_not_called()


@pytest.mark.asyncio
async def test_select_status_with_invalid_value_shows_alert_and_does_not_rerender():
    appointment_repo = FakeAppointmentRepository(_appointment())
    router = _router(appointment_repo)
    select_status = _find_handler(router, "select_status")

    callback_query = _callback_query()
    callback_data = ApptActionCB(
        action="select_status", appointment_id=1, mode="list", page=1, value="not-a-real-status", post_appt=True,
    )

    await select_status(callback_query, callback_data, AsyncMock(), _admin_user())

    callback_query.answer.assert_called_once_with("Некорректный статус.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_select_status_denies_access_when_appointment_not_found():
    appointment_repo = FakeAppointmentRepository(_appointment())
    appointment_repo.appointment = None
    router = _router(appointment_repo)
    select_status = _find_handler(router, "select_status")

    callback_query = _callback_query()
    callback_data = ApptActionCB(
        action="select_status", appointment_id=1, mode="list", page=1, value="cancelled", post_appt=True,
    )

    await select_status(callback_query, callback_data, AsyncMock(), _admin_user())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()


# --- open_status_menu ---

@pytest.mark.asyncio
async def test_open_status_menu_renders_menu_with_other_two_statuses():
    appointment_repo = FakeAppointmentRepository(_appointment(status=AppointmentStatus.COMPLETED))
    router = _router(appointment_repo)
    open_status_menu = _find_handler(router, "open_status_menu")

    callback_query = _callback_query()
    callback_data = ApptActionCB(action="status_menu", appointment_id=1, mode="list", page=1)

    await open_status_menu(callback_query, callback_data, AsyncMock(), _admin_user())

    reply_markup = callback_query.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [
        ApptActionCB.unpack(button.callback_data).value
        for row in reply_markup.inline_keyboard for button in row
        if button.callback_data.startswith("appt_act")
        and ApptActionCB.unpack(button.callback_data).action == "set_status"
    ]

    assert set(callback_datas) == {"cancelled", "no_show"}


@pytest.mark.asyncio
async def test_open_status_menu_denies_access_when_appointment_not_found():
    appointment_repo = FakeAppointmentRepository(_appointment())
    appointment_repo.appointment = None
    router = _router(appointment_repo)
    open_status_menu = _find_handler(router, "open_status_menu")

    callback_query = _callback_query()
    callback_data = ApptActionCB(action="status_menu", appointment_id=1, mode="list", page=1)

    await open_status_menu(callback_query, callback_data, AsyncMock(), _admin_user())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()


# --- finish_appointment: value-driven commit ---

@pytest.mark.asyncio
async def test_finish_appointment_commits_cancelled_when_value_is_cancelled():
    appointment_repo = FakeAppointmentRepository(_appointment())
    appointment_scheduler = AsyncMock()
    router = _router(appointment_repo, appointment_scheduler=appointment_scheduler)
    finish_appointment = _find_handler(router, "finish_appointment")

    callback_query = _callback_query()
    callback_data = ApptActionCB(
        action="finish_appointment", appointment_id=1, mode="list", page=1, value="cancelled",
    )

    await finish_appointment(callback_query, callback_data, AsyncMock(), _admin_user())

    assert appointment_repo.status_updates == [(1, AppointmentStatus.CANCELLED)]
    appointment_scheduler.resync_appointment_jobs.assert_awaited_once()
    resynced = appointment_scheduler.resync_appointment_jobs.await_args.args[0]
    assert resynced.status == AppointmentStatus.CANCELLED


@pytest.mark.asyncio
async def test_finish_appointment_commits_no_show_when_value_is_no_show():
    appointment_repo = FakeAppointmentRepository(_appointment())
    router = _router(appointment_repo)
    finish_appointment = _find_handler(router, "finish_appointment")

    callback_query = _callback_query()
    callback_data = ApptActionCB(
        action="finish_appointment", appointment_id=1, mode="list", page=1, value="no_show",
    )

    await finish_appointment(callback_query, callback_data, AsyncMock(), _admin_user())

    assert appointment_repo.status_updates == [(1, AppointmentStatus.NO_SHOW)]


@pytest.mark.asyncio
async def test_finish_appointment_falls_back_to_completed_when_value_missing():
    appointment_repo = FakeAppointmentRepository(_appointment())
    router = _router(appointment_repo)
    finish_appointment = _find_handler(router, "finish_appointment")

    callback_query = _callback_query()
    callback_data = ApptActionCB(action="finish_appointment", appointment_id=1, mode="list", page=1, value="")

    await finish_appointment(callback_query, callback_data, AsyncMock(), _admin_user())

    assert appointment_repo.status_updates == [(1, AppointmentStatus.COMPLETED)]


@pytest.mark.asyncio
async def test_finish_appointment_falls_back_to_completed_when_value_invalid():
    appointment_repo = FakeAppointmentRepository(_appointment())
    router = _router(appointment_repo)
    finish_appointment = _find_handler(router, "finish_appointment")

    callback_query = _callback_query()
    callback_data = ApptActionCB(
        action="finish_appointment", appointment_id=1, mode="list", page=1, value="not-a-real-status",
    )

    await finish_appointment(callback_query, callback_data, AsyncMock(), _admin_user())

    assert appointment_repo.status_updates == [(1, AppointmentStatus.COMPLETED)]
