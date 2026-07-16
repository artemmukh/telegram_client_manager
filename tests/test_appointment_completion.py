"""Tests for the post-appointment follow-up handlers (Да/Нет prompt).

"Да" opens the same appointment card in the post-appointment editing window
(status stays CONFIRMED). "Нет" finalizes the appointment as COMPLETED
immediately, since the auto-completion job no longer does this itself.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.admin.appointment_management.appointment_completion import (
    create_admin_completion_router,
)
from bot.keyboards.admin.record_management_kb.completion_followup_cb import CompletionFollowupCB
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


ADMIN_TELEGRAM_ID = 999
OTHER_ADMIN_TELEGRAM_ID = 1000


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


class FakeUserRepo:
    def __init__(self, admins=None):
        self.admins = admins or {
            ADMIN_TELEGRAM_ID: User(
                full_name="Петров Петр",
                phone="+998907654321",
                role=Role.ADMIN,
                telegram_user_id=ADMIN_TELEGRAM_ID,
                ID=1,
                clinic_id=1,
                clinic_name="Зуб Мудрости",
            ),
            OTHER_ADMIN_TELEGRAM_ID: User(
                full_name="Сидоров Сидор",
                phone="+998901112233",
                role=Role.ADMIN,
                telegram_user_id=OTHER_ADMIN_TELEGRAM_ID,
                ID=2,
                clinic_id=1,
                clinic_name="Зуб Мудрости",
            ),
        }

    async def get_user_by_telegram_id(self, telegram_user_id):
        return self.admins.get(telegram_user_id)


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=1, visibility_scope="own")


class FakeClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=1, name="Зуб Мудрости", token="t")


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _appointment(doctor_id=1):
    return Appointment(
        clinic_id=1,
        client_id=1,
        doctor_id=doctor_id,
        datetime="2026-07-10 10:00",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.CONFIRMED,
        id=1,
    )


def _callback_query(telegram_user_id=ADMIN_TELEGRAM_ID):
    callback_query = MagicMock()
    callback_query.from_user.id = telegram_user_id
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _router(appointment_repo):
    return create_admin_completion_router(appointment_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo())


@pytest.mark.asyncio
async def test_open_edit_keeps_status_confirmed_and_renders_post_appt_card():
    appointment_repo = FakeAppointmentRepository(_appointment())
    router = _router(appointment_repo)
    open_edit = _find_handler(router, "open_edit")

    callback_query = _callback_query()
    callback_data = CompletionFollowupCB(action="edit", appointment_id=1)

    await open_edit(callback_query, callback_data, AsyncMock())

    assert appointment_repo.appointment.status is AppointmentStatus.CONFIRMED
    assert appointment_repo.status_updates == []

    reply_markup = callback_query.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [button.callback_data for row in reply_markup.inline_keyboard for button in row]
    assert any("finish_appointment" in cb for cb in callback_datas)


@pytest.mark.asyncio
async def test_open_edit_denies_access_to_other_doctors_appointment():
    appointment_repo = FakeAppointmentRepository(_appointment(doctor_id=1))
    router = _router(appointment_repo)
    open_edit = _find_handler(router, "open_edit")

    callback_query = _callback_query(telegram_user_id=OTHER_ADMIN_TELEGRAM_ID)
    callback_data = CompletionFollowupCB(action="edit", appointment_id=1)

    await open_edit(callback_query, callback_data, AsyncMock())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    assert appointment_repo.appointment.status is AppointmentStatus.CONFIRMED


@pytest.mark.asyncio
async def test_skip_edit_finalizes_status_as_completed():
    appointment_repo = FakeAppointmentRepository(_appointment())
    router = _router(appointment_repo)
    skip_edit = _find_handler(router, "skip_edit")

    callback_query = _callback_query()
    callback_data = CompletionFollowupCB(action="skip", appointment_id=1)

    await skip_edit(callback_query, callback_data)

    assert appointment_repo.appointment.status is AppointmentStatus.COMPLETED
    assert appointment_repo.status_updates == [(1, AppointmentStatus.COMPLETED)]
    callback_query.message.edit_text.assert_called_once_with("Приём завершён.", reply_markup=None)


@pytest.mark.asyncio
async def test_skip_edit_denies_access_to_other_doctors_appointment():
    appointment_repo = FakeAppointmentRepository(_appointment(doctor_id=1))
    router = _router(appointment_repo)
    skip_edit = _find_handler(router, "skip_edit")

    callback_query = _callback_query(telegram_user_id=OTHER_ADMIN_TELEGRAM_ID)
    callback_data = CompletionFollowupCB(action="skip", appointment_id=1)

    await skip_edit(callback_query, callback_data)

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    assert appointment_repo.appointment.status is AppointmentStatus.CONFIRMED
    assert appointment_repo.status_updates == []
