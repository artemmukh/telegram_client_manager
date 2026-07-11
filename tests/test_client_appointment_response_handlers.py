import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from unittest.mock import AsyncMock, MagicMock

from bot.models.appointment import Appointment
from bot.models.user import User
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


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
