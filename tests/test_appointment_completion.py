"""Tests for the post-appointment follow-up handlers (Да/Нет prompt).

Both "Да" and "Нет" now atomically finalize the appointment as COMPLETED via
AppointmentManagement.complete_appointment_by_admin() before doing anything
else. "Да" then re-opens the post-appointment editing window (status/service/
price corrections) on top of the now-COMPLETED appointment; "Нет" just closes
out the follow-up prompt. If another staff member's decision already landed
first (AppointmentAlreadyDecidedError), both branches show the same fixed
alert and skip their normal success rendering.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.admin.appointment_management.appointment_completion import (
    create_admin_completion_router,
)
from bot.keyboards.admin.record_management_kb.completion_followup_cb import CompletionFollowupCB
from bot.models.appointment import Appointment
from bot.models.appointment_notification import AppointmentNotification
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


ADMIN_TELEGRAM_ID = 999
OTHER_ADMIN_TELEGRAM_ID = 1000

ALREADY_DECIDED_ALERT = "Запись уже автозавершена, вы можете скорректировать её в «Завершённые»"


class FakeAppointmentRepository:
    def __init__(self, appointment, notifications=None):
        self.appointment = appointment
        self.status_updates = []
        self.notifications = list(notifications or [])

    async def get_appointment_by_id(self, appointment_id):
        return self.appointment

    async def get_appointments_by_doctor_and_date(self, doctor_id, date):
        return []

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.appointment.status = status
        self.status_updates.append((appointment_id, status))

    async def try_complete_appointment(self, appointment_id, decided_by_user_id, status_updated_at):
        # Deliberately does not mutate self.appointment -- AppointmentManagement.
        # complete_appointment_by_admin() applies the equivalent field updates
        # itself afterward, mirroring the real repository which only touches
        # the DB row, never the caller's Python object.
        finalized = {
            AppointmentStatus.CANCELLED,
            AppointmentStatus.COMPLETED,
            AppointmentStatus.NO_SHOW,
            AppointmentStatus.EXPIRED,
        }
        if self.appointment.status in finalized:
            return False

        self.status_updates.append((appointment_id, AppointmentStatus.COMPLETED))
        return True

    async def get_appointment_notifications(self, appointment_id, kind):
        return self.notifications


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
        self.by_id = {user.ID: user for user in self.admins.values()}

    async def get_user_by_telegram_id(self, telegram_user_id):
        return self.admins.get(telegram_user_id)

    async def get_user_by_id(self, user_id):
        return self.by_id.get(user_id)


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


def _admin_user():
    return User(full_name="Петров Петр", phone="+998907654321", role=Role.ADMIN, telegram_user_id=ADMIN_TELEGRAM_ID, ID=1)


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


def _router(appointment_repo, appointment_scheduler=None, notification_service=None):
    return create_admin_completion_router(
        appointment_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(),
        appointment_scheduler, notification_service,
    )


@pytest.mark.asyncio
async def test_open_edit_completes_appointment_and_renders_post_appt_card():
    appointment_repo = FakeAppointmentRepository(_appointment())
    router = _router(appointment_repo)
    open_edit = _find_handler(router, "open_edit")

    callback_query = _callback_query()
    callback_data = CompletionFollowupCB(action="edit", appointment_id=1)

    await open_edit(callback_query, callback_data, AsyncMock(), _admin_user())

    assert appointment_repo.appointment.status is AppointmentStatus.COMPLETED
    assert appointment_repo.status_updates == [(1, AppointmentStatus.COMPLETED)]

    reply_markup = callback_query.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [button.callback_data for row in reply_markup.inline_keyboard for button in row]
    assert any("finish_appointment" in cb for cb in callback_datas)


@pytest.mark.asyncio
async def test_open_edit_resyncs_jobs_when_scheduler_provided():
    appointment_repo = FakeAppointmentRepository(_appointment())
    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()
    router = _router(appointment_repo, appointment_scheduler)
    open_edit = _find_handler(router, "open_edit")

    callback_query = _callback_query()
    callback_data = CompletionFollowupCB(action="edit", appointment_id=1)

    await open_edit(callback_query, callback_data, AsyncMock(), _admin_user())

    appointment_scheduler.resync_appointment_jobs.assert_awaited_once()
    resynced_appointment = appointment_scheduler.resync_appointment_jobs.call_args.args[0]
    assert resynced_appointment.status is AppointmentStatus.COMPLETED


@pytest.mark.asyncio
async def test_open_edit_invalidates_sibling_notifications_on_success():
    appointment_repo = FakeAppointmentRepository(
        _appointment(),
        notifications=[
            AppointmentNotification(appointment_id=1, chat_id=555, message_id=777, kind="completion"),
        ],
    )
    notification_service = MagicMock()
    notification_service.invalidate_stale_decision_message = AsyncMock()
    router = _router(appointment_repo, notification_service=notification_service)
    open_edit = _find_handler(router, "open_edit")

    callback_query = _callback_query()
    callback_data = CompletionFollowupCB(action="edit", appointment_id=1)

    await open_edit(callback_query, callback_data, AsyncMock(), _admin_user())

    notification_service.invalidate_stale_decision_message.assert_awaited_once_with(
        555, 777, "Доктор Петров Петр", "приём завершён",
    )


@pytest.mark.asyncio
async def test_open_edit_shows_alert_and_does_not_render_card_when_already_decided():
    appointment = _appointment()
    appointment.status = AppointmentStatus.COMPLETED
    appointment_repo = FakeAppointmentRepository(appointment)
    notification_service = MagicMock()
    notification_service.invalidate_stale_decision_message = AsyncMock()
    router = _router(appointment_repo, notification_service=notification_service)
    open_edit = _find_handler(router, "open_edit")

    callback_query = _callback_query()
    callback_query.message.chat.id = 111
    callback_query.message.message_id = 222
    callback_data = CompletionFollowupCB(action="edit", appointment_id=1)

    await open_edit(callback_query, callback_data, AsyncMock(), _admin_user())

    callback_query.answer.assert_called_once_with(ALREADY_DECIDED_ALERT, show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    assert appointment_repo.status_updates == []
    notification_service.invalidate_stale_decision_message.assert_awaited_once_with(
        111, 222, "Другой сотрудник", "приём завершён",
    )


@pytest.mark.asyncio
async def test_open_edit_denies_access_to_other_doctors_appointment():
    appointment_repo = FakeAppointmentRepository(_appointment(doctor_id=1))
    router = _router(appointment_repo)
    open_edit = _find_handler(router, "open_edit")

    callback_query = _callback_query(telegram_user_id=OTHER_ADMIN_TELEGRAM_ID)
    callback_data = CompletionFollowupCB(action="edit", appointment_id=1)

    await open_edit(callback_query, callback_data, AsyncMock(), _admin_user())

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

    await skip_edit(callback_query, callback_data, _admin_user())

    assert appointment_repo.appointment.status is AppointmentStatus.COMPLETED
    assert appointment_repo.status_updates == [(1, AppointmentStatus.COMPLETED)]
    callback_query.message.edit_text.assert_called_once_with("Приём завершён.", reply_markup=None)


@pytest.mark.asyncio
async def test_skip_edit_resyncs_jobs_when_scheduler_provided():
    appointment_repo = FakeAppointmentRepository(_appointment())
    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()
    router = _router(appointment_repo, appointment_scheduler)
    skip_edit = _find_handler(router, "skip_edit")

    callback_query = _callback_query()
    callback_data = CompletionFollowupCB(action="skip", appointment_id=1)

    await skip_edit(callback_query, callback_data, _admin_user())

    appointment_scheduler.resync_appointment_jobs.assert_awaited_once()
    resynced_appointment = appointment_scheduler.resync_appointment_jobs.call_args.args[0]
    assert resynced_appointment.status is AppointmentStatus.COMPLETED


@pytest.mark.asyncio
async def test_skip_edit_denies_access_to_other_doctors_appointment():
    appointment_repo = FakeAppointmentRepository(_appointment(doctor_id=1))
    router = _router(appointment_repo)
    skip_edit = _find_handler(router, "skip_edit")

    callback_query = _callback_query(telegram_user_id=OTHER_ADMIN_TELEGRAM_ID)
    callback_data = CompletionFollowupCB(action="skip", appointment_id=1)

    await skip_edit(callback_query, callback_data, _admin_user())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    assert appointment_repo.appointment.status is AppointmentStatus.CONFIRMED
    assert appointment_repo.status_updates == []


@pytest.mark.asyncio
async def test_skip_edit_shows_alert_and_does_not_finalize_when_already_decided():
    appointment = _appointment()
    appointment.status = AppointmentStatus.COMPLETED
    appointment_repo = FakeAppointmentRepository(appointment)
    notification_service = MagicMock()
    notification_service.invalidate_stale_decision_message = AsyncMock()
    router = _router(appointment_repo, notification_service=notification_service)
    skip_edit = _find_handler(router, "skip_edit")

    callback_query = _callback_query()
    callback_query.message.chat.id = 111
    callback_query.message.message_id = 222
    callback_data = CompletionFollowupCB(action="skip", appointment_id=1)

    await skip_edit(callback_query, callback_data, _admin_user())

    callback_query.answer.assert_called_once_with(ALREADY_DECIDED_ALERT, show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    assert appointment_repo.status_updates == []
    notification_service.invalidate_stale_decision_message.assert_awaited_once_with(
        111, 222, "Другой сотрудник", "приём завершён",
    )
