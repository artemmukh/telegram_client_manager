import pytest
from aiogram.types import ReplyParameters

from bot.exceptions.appointment_exceptions import NotificationDeliveryError
from bot.models.appointment import Appointment
from bot.models.user import User
from bot.services.appointment.appointment_notifications import (
    REMINDER_TEXT,
    AppointmentNotificationService,
)
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


class FakeBotMessage:
    def __init__(self, text, reply_markup, message_id=777):
        self.text = text
        self.reply_markup = reply_markup
        self.message_id = message_id


class FakeBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text, reply_markup=None, reply_parameters=None):
        self.sent_messages.append({
            'chat_id': chat_id,
            'text': text,
            'reply_markup': reply_markup,
            'reply_parameters': reply_parameters,
        })
        return FakeBotMessage(text, reply_markup)


class FakeUserRepo:
    def __init__(self, user=None):
        self.user = user

    async def get_client_by_id(self, client_id):
        return self.user


class FakeAppointmentRepo:
    pass


class FailingBot:
    async def send_message(self, *args, **kwargs):
        raise RuntimeError("Telegram API error")


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

    result = await service.notify_client_appointment_with_buttons(appointment)

    assert result == 777
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

    result = await service.notify_client_appointment_with_buttons(appointment)

    assert result is None
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

    result = await service.notify_client_appointment_with_buttons(appointment)

    assert result is None
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


@pytest.mark.asyncio
async def test_notify_client_reminder_without_buttons_replies_when_message_id_set():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_reminder_without_buttons(appointment)

    assert result is True
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert msg['text'] == REMINDER_TEXT
    assert msg['reply_markup'] is None
    assert msg['reply_parameters'] == ReplyParameters(
        message_id=555,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_notify_client_reminder_without_buttons_no_reply_parameters_when_message_id_missing():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = None

    result = await service.notify_client_reminder_without_buttons(appointment)

    assert result is True
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['text'] == REMINDER_TEXT
    assert msg['reply_markup'] is None
    assert msg['reply_parameters'] is None


@pytest.mark.asyncio
async def test_notify_client_reminder_without_buttons_returns_false_when_no_telegram_id():
    bot = FakeBot()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reminder_without_buttons(appointment)

    assert result is False
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_reminder_with_buttons_replies_when_message_id_set():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_reminder_with_buttons(appointment)

    assert result is True
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert msg['text'] == REMINDER_TEXT
    assert msg['reply_markup'] is not None
    assert msg['reply_parameters'] == ReplyParameters(
        message_id=555,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_notify_client_reminder_with_buttons_no_reply_parameters_when_message_id_missing():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = None

    result = await service.notify_client_reminder_with_buttons(appointment)

    assert result is True
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['text'] == REMINDER_TEXT
    assert msg['reply_markup'] is not None
    assert msg['reply_parameters'] is None


@pytest.mark.asyncio
async def test_notify_client_reminder_with_buttons_returns_false_when_no_telegram_id():
    bot = FakeBot()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reminder_with_buttons(appointment)

    assert result is False
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_cancelled_by_admin_replies_when_message_id_set():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_cancelled_by_admin(appointment)

    assert result is True
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "отменена администратором" in msg['text']
    assert msg['reply_markup'] is None
    assert msg['reply_parameters'] == ReplyParameters(
        message_id=555,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_notify_client_appointment_cancelled_by_admin_no_reply_parameters_when_message_id_missing():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = None

    result = await service.notify_client_appointment_cancelled_by_admin(appointment)

    assert result is True
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "отменена администратором" in msg['text']
    assert msg['reply_markup'] is None
    assert msg['reply_parameters'] is None


@pytest.mark.asyncio
async def test_notify_client_appointment_cancelled_by_admin_returns_false_when_no_telegram_id():
    bot = FakeBot()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_appointment_cancelled_by_admin(appointment)

    assert result is False
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_changed_sends_updated_details():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_changed(appointment)

    assert result is True
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "изменены администратором" in msg['text']
    assert "2026-07-10 14:30" in msg['text']
    assert "Консультация" in msg['text']
    assert msg['reply_markup'] is None
    assert msg['reply_parameters'] == ReplyParameters(
        message_id=555,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_notify_client_appointment_changed_no_reply_parameters_when_message_id_missing():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = None

    result = await service.notify_client_appointment_changed(appointment)

    assert result is True
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "изменены администратором" in msg['text']
    assert "2026-07-10 14:30" in msg['text']
    assert "Консультация" in msg['text']
    assert msg['reply_markup'] is None
    assert msg['reply_parameters'] is None


@pytest.mark.asyncio
async def test_notify_client_appointment_changed_returns_false_when_no_telegram_id():
    bot = FakeBot()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_appointment_changed(appointment)

    assert result is False
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_staff_new_booking_request_sends_message():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    await service.notify_staff_new_booking_request(67890, appointment, "Иванов Иван")

    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 67890
    assert "Новая заявка на запись" in msg['text']
    assert "Иванов Иван" in msg['text']
    assert "2026-07-10 14:30" in msg['text']
    assert "Консультация" in msg['text']


@pytest.mark.asyncio
async def test_notify_staff_new_booking_request_raises_on_send_failure():
    bot = FailingBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    with pytest.raises(NotificationDeliveryError):
        await service.notify_staff_new_booking_request(67890, appointment, "Иванов Иван")


@pytest.mark.asyncio
async def test_notify_client_pending_request_expired_sends_message():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_pending_request_expired(appointment)

    assert result is True
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "истекла" in msg['text']


@pytest.mark.asyncio
async def test_notify_client_pending_request_expired_returns_false_when_user_not_found():
    bot = FakeBot()
    user_repo = FakeUserRepo(None)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_pending_request_expired(appointment)

    assert result is False
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_pending_request_expired_returns_false_when_telegram_id_missing():
    bot = FakeBot()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_pending_request_expired(appointment)

    assert result is False
    assert len(bot.sent_messages) == 0
