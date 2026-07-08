"""
Integration tests for Phase 2: Appointment Notifications & Status Lifecycle
"""
import pytest

from bot.models.appointment import Appointment
from bot.models.user import User
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import AppointmentNotificationService
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


class FakeBotForIntegration:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent_messages.append({
            'chat_id': chat_id,
            'text': text,
            'reply_markup': reply_markup
        })


class FakeAppointmentRepoForIntegration:
    def __init__(self):
        self.appointments = []
        self.status_updates = []

    async def create_appointment(self, appointment):
        appointment.id = len(self.appointments) + 1
        self.appointments.append(appointment)

    async def get_appointment_by_id(self, appointment_id):
        return next((a for a in self.appointments if a.id == appointment_id), None)

    async def appointment_exists(self, appointment_id):
        return any(a.id == appointment_id for a in self.appointments)

    async def update_appointment_status(self, appointment_id, status):
        for appt in self.appointments:
            if appt.id == appointment_id:
                appt.status = status
                self.status_updates.append((appointment_id, status))

    async def get_appointments_by_client_id(self, client_id):
        return [a for a in self.appointments if a.client_id == client_id]


class FakeUserRepoForIntegration:
    def __init__(self):
        self.users = {}

    def add_user(self, user):
        self.users[user.ID] = user

    async def get_client_by_id(self, client_id):
        return self.users.get(client_id)

    async def get_client_by_phone(self, phone):
        for user in self.users.values():
            if user.phone == phone:
                return user
        return None


class FakeStaffRepoForIntegration:
    pass


class FakeClinicRepoForIntegration:
    pass


@pytest.mark.asyncio
async def test_phase2_complete_workflow():
    """Test complete Phase 2 workflow: create appointment, client responds, status updates."""

    # Setup
    bot = FakeBotForIntegration()
    appt_repo = FakeAppointmentRepoForIntegration()
    user_repo = FakeUserRepoForIntegration()
    staff_repo = FakeStaffRepoForIntegration()
    clinic_repo = FakeClinicRepoForIntegration()

    # Create client
    client = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=12345,
        ID=1
    )
    user_repo.add_user(client)

    # Create admin
    admin = User(
        full_name="Доктор Петров",
        phone="+998901234568",
        role=Role.ADMIN,
        telegram_user_id=54321,
        ID=999
    )

    # Create services
    appointment_mgmt = AppointmentManagement(
        appt_repo, user_repo, staff_repo, clinic_repo
    )
    notification_svc = AppointmentNotificationService(bot, user_repo, appt_repo)

    # Step 1: Create appointment
    appointment = Appointment(
        clinic_id=1,
        client_id=1,
        datetime="2026-07-10 14:30",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        clinic_name="Зуб Мудрости"
    )
    await appt_repo.create_appointment(appointment)

    # Step 2: Notify client
    notification_sent = await notification_svc.notify_client_appointment_with_buttons(appointment)
    assert notification_sent is True
    assert len(bot.sent_messages) == 1
    assert bot.sent_messages[0]['chat_id'] == 12345
    assert "Вам назначена запись на прием" in bot.sent_messages[0]['text']
    assert "✅ Приду" in str(bot.sent_messages[0]['reply_markup'])

    # Step 3: Client confirms appointment
    appointment = await appointment_mgmt.update_status(
        appointment.id, AppointmentStatus.CONFIRMED
    )
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates[-1] == (appointment.id, AppointmentStatus.CONFIRMED)

    # Step 4: Get appointment info for notification
    appt_with_client, retrieved_client = await appointment_mgmt.get_appointment_with_client_info(
        appointment.id
    )
    assert retrieved_client.full_name == "Иванов Иван"

    # Step 5: Notify admin of confirmation
    await notification_svc.notify_admin_confirmation(
        54321, appt_with_client, retrieved_client.full_name
    )
    assert len(bot.sent_messages) == 2
    assert bot.sent_messages[1]['chat_id'] == 54321
    assert "подтвердил запись" in bot.sent_messages[1]['text']


@pytest.mark.asyncio
async def test_phase2_cancellation_workflow():
    """Test Phase 2 cancellation workflow."""

    # Setup
    bot = FakeBotForIntegration()
    appt_repo = FakeAppointmentRepoForIntegration()
    user_repo = FakeUserRepoForIntegration()
    staff_repo = FakeStaffRepoForIntegration()
    clinic_repo = FakeClinicRepoForIntegration()

    # Create client
    client = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=12345,
        ID=1
    )
    user_repo.add_user(client)

    # Create services
    appointment_mgmt = AppointmentManagement(
        appt_repo, user_repo, staff_repo, clinic_repo
    )
    notification_svc = AppointmentNotificationService(bot, user_repo, appt_repo)

    # Step 1: Create appointment
    appointment = Appointment(
        clinic_id=1,
        client_id=1,
        datetime="2026-07-10 14:30",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        clinic_name="Зуб Мудрости"
    )
    await appt_repo.create_appointment(appointment)

    # Step 2: Client cancels appointment
    appointment = await appointment_mgmt.update_status(
        appointment.id, AppointmentStatus.CANCELLED
    )
    assert appointment.status == AppointmentStatus.CANCELLED

    # Step 3: Get appointment info for notification
    appt_with_client, retrieved_client = await appointment_mgmt.get_appointment_with_client_info(
        appointment.id
    )
    assert retrieved_client is not None

    # Step 4: Notify admin of cancellation
    await notification_svc.notify_admin_cancellation(
        54321, appt_with_client, retrieved_client.full_name
    )
    assert len(bot.sent_messages) == 1
    assert bot.sent_messages[0]['chat_id'] == 54321
    assert "отменил запись" in bot.sent_messages[0]['text']
    assert "Иванов Иван" in bot.sent_messages[0]['text']
