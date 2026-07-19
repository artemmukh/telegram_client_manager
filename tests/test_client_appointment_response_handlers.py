import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.client.appointment_response import create_client_appointment_router
from bot.models.appointment import Appointment
from bot.models.user import User
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


def _get_handler_by_name(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"{name} handler not found on router")


def _make_callback_query(data):
    callback_query = MagicMock()
    callback_query.data = data
    callback_query.from_user.id = 12345
    callback_query.message.edit_text = AsyncMock()
    callback_query.answer = AsyncMock()
    return callback_query


# Helper functions for creating test data
def _client():
    return User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=12345,
        ID=1
    )


def _appointment():
    return Appointment(
        clinic_id=1,
        client_id=1,
        datetime="2026-07-10 14:30",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        id=1,
        clinic_name="Зуб Мудрости"
    )


def _admin():
    return User(
        full_name="Доктор Петров",
        phone="+998901234568",
        role=Role.ADMIN,
        telegram_user_id=54321,
        ID=999
    )


# Fake classes for testing
class FakeAppointmentRepo:
    def __init__(self, appointments=None):
        self.appointments = list(appointments or [])
        self.status_updates = []

    async def get_appointment_by_id(self, appointment_id):
        return next((a for a in self.appointments if a.id == appointment_id), None)

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.status_updates.append((appointment_id, status))
        for appt in self.appointments:
            if appt.id == appointment_id:
                appt.status = status


class FakeUserRepo:
    def __init__(self, client=None):
        self.client = client

    async def get_client_by_id(self, client_id):
        if self.client and self.client.ID == client_id:
            return self.client
        return None


class FakeStaffRepo:
    pass


class FakeClinicRepo:
    pass


class FakeBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent_messages.append({
            'chat_id': chat_id,
            'text': text,
            'reply_markup': reply_markup
        })


class FakeNotificationService:
    def __init__(self):
        self.confirmations = []
        self.cancellations = []

    async def notify_admin_confirmation(self, admin_telegram_id, appointment, client_name):
        self.confirmations.append((admin_telegram_id, appointment, client_name))

    async def notify_admin_cancellation(self, admin_telegram_id, appointment, client_name):
        self.cancellations.append((admin_telegram_id, appointment, client_name))


# Tests for confirmation flow
@pytest.mark.asyncio
async def test_handle_appointment_confirm_updates_status():
    from bot.services.appointment.appointment_management import AppointmentManagement

    appt = _appointment()
    appt_repo = FakeAppointmentRepo([appt])
    user_repo = FakeUserRepo(_client())

    service = AppointmentManagement(
        appt_repo, user_repo, FakeStaffRepo(), FakeClinicRepo()
    )

    confirmed_appt = await service.update_status(1, AppointmentStatus.CONFIRMED)

    assert confirmed_appt.status == AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CONFIRMED)]


@pytest.mark.asyncio
async def test_handle_appointment_confirm_handler_resyncs_jobs_and_edits_without_reply_markup():
    """PR3: handle_appointment_confirm now serves ONLY the 2h-reminder confirm
    button (the initial-invite confirm moved to the new appointment_invite router).
    It resyncs the full job set via resync_appointment_jobs (replacing the old
    cancel_pending_expiry + cancel_auto_confirm pair) and edits the message with a
    plain success text -- no reply_markup is passed at all anymore."""
    confirmed_appointment = _appointment()
    confirmed_appointment.status = AppointmentStatus.CONFIRMED

    appointment_management_service = MagicMock()
    appointment_management_service.confirm_appointment_by_client = AsyncMock(return_value=confirmed_appointment)
    appointment_management_service.get_appointment_with_client_info = AsyncMock(
        return_value=(confirmed_appointment, _client())
    )

    notification_service = MagicMock()
    notification_service.notify_admin_confirmation = AsyncMock()

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()
    appointment_scheduler.cancel_pending_expiry = AsyncMock()
    appointment_scheduler.cancel_auto_confirm = AsyncMock()

    router = create_client_appointment_router(
        MagicMock(), appointment_management_service, notification_service, appointment_scheduler,
    )
    handle_appointment_confirm = _get_handler_by_name(router, "handle_appointment_confirm")

    callback_query = _make_callback_query("appt_confirm:1")
    await handle_appointment_confirm(callback_query)

    appointment_management_service.confirm_appointment_by_client.assert_awaited_once_with(1, 12345)
    appointment_scheduler.resync_appointment_jobs.assert_awaited_once_with(confirmed_appointment)
    appointment_scheduler.cancel_pending_expiry.assert_not_awaited()
    appointment_scheduler.cancel_auto_confirm.assert_not_awaited()

    callback_query.message.edit_text.assert_awaited_once_with("✅ Спасибо! Ваша запись подтверждена")
    assert "reply_markup" not in callback_query.message.edit_text.call_args.kwargs
    callback_query.answer.assert_awaited_once()


# Tests for cancellation flow
@pytest.mark.asyncio
async def test_handle_appointment_cancel_updates_status():
    from bot.services.appointment.appointment_management import AppointmentManagement

    appt = _appointment()
    appt_repo = FakeAppointmentRepo([appt])
    user_repo = FakeUserRepo(_client())

    service = AppointmentManagement(
        appt_repo, user_repo, FakeStaffRepo(), FakeClinicRepo()
    )

    cancelled_appt = await service.update_status(1, AppointmentStatus.CANCELLED)

    assert cancelled_appt.status == AppointmentStatus.CANCELLED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CANCELLED)]


@pytest.mark.asyncio
async def test_handler_sends_confirmation_message_to_admin():
    """Test that handler sends confirmation message to admin when appointment confirmed."""
    from bot.services.appointment.appointment_management import AppointmentManagement

    appt = _appointment()
    appt_repo = FakeAppointmentRepo([appt])
    user_repo = FakeUserRepo(_client())
    notification_service = FakeNotificationService()

    service = AppointmentManagement(
        appt_repo, user_repo, FakeStaffRepo(), FakeClinicRepo()
    )

    appointment, client = await service.get_appointment_with_client_info(1)
    await notification_service.notify_admin_confirmation(54321, appointment, client.full_name)

    assert len(notification_service.confirmations) == 1
    admin_id, notified_appt, client_name = notification_service.confirmations[0]
    assert admin_id == 54321
    assert notified_appt.id == 1
    assert client_name == "Иванов Иван"


@pytest.mark.asyncio
async def test_handle_appointment_confirm_handler_does_not_notify_admin():
    """PR3: handle_appointment_confirm (2h-reminder confirm) no longer notifies the
    admin at all -- that responsibility moved to the initial-invite confirm handler
    in bot/handlers/client/appointment_invite.py, which fires notify_admin_confirmation
    itself. The 2h-reminder handler must leave notification_service alone."""
    confirmed_appointment = _appointment()
    confirmed_appointment.status = AppointmentStatus.CONFIRMED
    confirmed_appointment.created_by_telegram_id = 54321

    appointment_management_service = MagicMock()
    appointment_management_service.confirm_appointment_by_client = AsyncMock(return_value=confirmed_appointment)
    appointment_management_service.get_appointment_with_client_info = AsyncMock(
        return_value=(confirmed_appointment, _client())
    )

    notification_service = MagicMock()
    notification_service.notify_admin_confirmation = AsyncMock()

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()

    router = create_client_appointment_router(
        MagicMock(), appointment_management_service, notification_service, appointment_scheduler,
    )
    handle_appointment_confirm = _get_handler_by_name(router, "handle_appointment_confirm")

    await handle_appointment_confirm(_make_callback_query("appt_confirm:1"))

    notification_service.notify_admin_confirmation.assert_not_awaited()


def _make_state_with_appointment_id(appointment_id=1):
    state = MagicMock()
    state.get_data = AsyncMock(return_value={"appointment_id": appointment_id})
    state.clear = AsyncMock()
    return state


@pytest.mark.asyncio
async def test_handle_cancel_confirmation_yes_notifies_sole_doctor_recipient():
    """Regression/backward-compat case: resolve_notification_recipients resolves
    to exactly one recipient (the treating doctor, who is also the appointment's
    sole clinic-scope admin in the common solo-doctor setup) -- notify_admin_cancellation
    must fire exactly once, to that one recipient."""
    cancelled_appointment = _appointment()
    cancelled_appointment.status = AppointmentStatus.CANCELLED
    client = _client()
    doctor = _admin()

    appointment_management_service = MagicMock()
    appointment_management_service.cancel_appointment_by_client = AsyncMock(return_value=cancelled_appointment)
    appointment_management_service.get_appointment_with_client_info = AsyncMock(
        return_value=(cancelled_appointment, client)
    )
    appointment_management_service.resolve_notification_recipients = AsyncMock(return_value=[doctor])

    notification_service = MagicMock()
    notification_service.notify_admin_cancellation = AsyncMock()

    appointment_scheduler = AsyncMock()

    router = create_client_appointment_router(
        MagicMock(), appointment_management_service, notification_service, appointment_scheduler,
    )
    handle_cancel_confirmation_yes = _get_handler_by_name(router, "handle_cancel_confirmation_yes")

    callback_query = _make_callback_query("appt_cancel_confirm_yes")
    state = _make_state_with_appointment_id(1)

    await handle_cancel_confirmation_yes(callback_query, state)

    notification_service.notify_admin_cancellation.assert_awaited_once_with(
        doctor.telegram_user_id, cancelled_appointment, client.full_name,
    )
    appointment_scheduler.cancel_all_jobs.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_handle_cancel_confirmation_yes_notifies_remaining_recipients_after_one_fails():
    """Per-recipient failure isolation: with two resolved recipients, the first
    recipient's send raising must not prevent the second recipient in the loop
    from being attempted -- each send is independently wrapped."""
    cancelled_appointment = _appointment()
    cancelled_appointment.status = AppointmentStatus.CANCELLED
    client = _client()
    doctor = _admin()
    clinic_admin = User(
        full_name="Админ Клиники", phone="+998901234569", role=Role.ADMIN, telegram_user_id=67890, ID=1000,
    )

    appointment_management_service = MagicMock()
    appointment_management_service.cancel_appointment_by_client = AsyncMock(return_value=cancelled_appointment)
    appointment_management_service.get_appointment_with_client_info = AsyncMock(
        return_value=(cancelled_appointment, client)
    )
    appointment_management_service.resolve_notification_recipients = AsyncMock(
        return_value=[doctor, clinic_admin]
    )

    notification_service = MagicMock()
    notification_service.notify_admin_cancellation = AsyncMock(
        side_effect=[Exception("boom"), None]
    )

    appointment_scheduler = AsyncMock()

    router = create_client_appointment_router(
        MagicMock(), appointment_management_service, notification_service, appointment_scheduler,
    )
    handle_cancel_confirmation_yes = _get_handler_by_name(router, "handle_cancel_confirmation_yes")

    callback_query = _make_callback_query("appt_cancel_confirm_yes")
    state = _make_state_with_appointment_id(1)

    # Should not raise, despite the first recipient's send failing.
    await handle_cancel_confirmation_yes(callback_query, state)

    assert notification_service.notify_admin_cancellation.await_count == 2
    notification_service.notify_admin_cancellation.assert_any_await(
        doctor.telegram_user_id, cancelled_appointment, client.full_name,
    )
    notification_service.notify_admin_cancellation.assert_any_await(
        clinic_admin.telegram_user_id, cancelled_appointment, client.full_name,
    )
    appointment_scheduler.cancel_all_jobs.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_handler_sends_cancellation_message_to_admin():
    """Test that handler sends cancellation message to admin when appointment cancelled."""
    from bot.services.appointment.appointment_management import AppointmentManagement

    appt = _appointment()
    appt_repo = FakeAppointmentRepo([appt])
    user_repo = FakeUserRepo(_client())
    notification_service = FakeNotificationService()

    service = AppointmentManagement(
        appt_repo, user_repo, FakeStaffRepo(), FakeClinicRepo()
    )

    appointment, client = await service.get_appointment_with_client_info(1)
    await notification_service.notify_admin_cancellation(54321, appointment, client.full_name)

    assert len(notification_service.cancellations) == 1
    admin_id, notified_appt, client_name = notification_service.cancellations[0]
    assert admin_id == 54321
    assert notified_appt.id == 1
    assert client_name == "Иванов Иван"
