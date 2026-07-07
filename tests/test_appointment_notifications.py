import pytest

from bot.models.appointment import Appointment
from bot.models.user import User
from bot.services.appointment.appointment_notifications import AppointmentNotificationService
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


class FakeBotMessage:
    def __init__(self, text, reply_markup):
        self.text = text
        self.reply_markup = reply_markup


class FakeBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent_messages.append({
            'chat_id': chat_id,
            'text': text,
            'reply_markup': reply_markup
        })
        return FakeBotMessage(text, reply_markup)


class FakeUserRepo:
    def __init__(self, user=None):
        self.user = user

    async def get_client_by_id(self, client_id):
        return self.user


class FakeAppointmentRepo:
    pass


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


@pytest.mark.asyncio
async def test_notify_client_appointment_sends_message_with_buttons():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_appointment(appointment)

    assert result is True
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "Вам назначена запись на прием" in msg['text']
    assert "2026-07-10 14:30" in msg['text']
    assert "Консультация" in msg['text']
    assert msg['reply_markup'] is not None


@pytest.mark.asyncio
async def test_notify_client_appointment_returns_false_when_user_not_found():
    bot = FakeBot()
    user_repo = FakeUserRepo(None)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_appointment(appointment)

    assert result is False
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_returns_false_when_telegram_id_missing():
    bot = FakeBot()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_appointment(appointment)

    assert result is False
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_admin_cancellation():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    await service.notify_admin_cancellation(54321, appointment, "Иванов Иван")

    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 54321
    assert "Иванов Иван" in msg['text']
    assert "отменил" in msg['text']
    assert "2026-07-10 14:30" in msg['text']
