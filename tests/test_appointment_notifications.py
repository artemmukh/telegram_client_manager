import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ReplyParameters

from bot.exceptions.appointment_exceptions import NotificationDeliveryError
from bot.models.appointment import Appointment
from bot.models.user import User
from bot.keyboards.client.appointment_response_kb import (
    appointment_reminder_details_kb,
    appointment_reminder_with_buttons_kb,
)
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
    def __init__(self, user=None, admin=None):
        self.user = user
        self.admin = admin

    async def get_client_by_id(self, client_id):
        return self.user

    async def get_user_by_id(self, user_id):
        return self.admin


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


def _admin():
    return User(
        full_name="Доктор Петров",
        phone="+998901234568",
        role=Role.ADMIN,
        telegram_user_id=54321,
        ID=999
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
    assert msg['text'] == "Клиент Иванов Иван отменил запись."


@pytest.mark.asyncio
async def test_notify_admin_cancellation_replies_when_admin_message_id_set():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = 888

    await service.notify_admin_cancellation(54321, appointment, "Иванов Иван")

    msg = bot.sent_messages[0]
    assert msg['reply_parameters'] == ReplyParameters(
        message_id=888,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_notify_admin_cancellation_no_reply_parameters_when_admin_message_id_missing():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = None

    await service.notify_admin_cancellation(54321, appointment, "Иванов Иван")

    msg = bot.sent_messages[0]
    assert msg['reply_parameters'] is None


@pytest.mark.asyncio
async def test_notify_admin_confirmation_sends_short_text():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    await service.notify_admin_confirmation(54321, appointment, "Иванов Иван")

    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 54321
    assert msg['text'] == "Клиент Иванов Иван подтвердил запись."


@pytest.mark.asyncio
async def test_notify_admin_confirmation_replies_when_admin_message_id_set():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = 888

    await service.notify_admin_confirmation(54321, appointment, "Иванов Иван")

    msg = bot.sent_messages[0]
    assert msg['reply_parameters'] == ReplyParameters(
        message_id=888,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_notify_admin_confirmation_no_reply_parameters_when_admin_message_id_missing():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = None

    await service.notify_admin_confirmation(54321, appointment, "Иванов Иван")

    msg = bot.sent_messages[0]
    assert msg['reply_parameters'] is None


@pytest.mark.asyncio
async def test_notify_admin_completion_sends_followup_prompt_with_keyboard():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    await service.notify_admin_completion(54321, appointment)

    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 54321
    assert msg['text'] == "Приём завершён. Дополнить информацию об услуге?"
    assert msg['reply_markup'] is not None


@pytest.mark.asyncio
async def test_notify_admin_completion_replies_when_admin_message_id_set():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = 888

    await service.notify_admin_completion(54321, appointment)

    msg = bot.sent_messages[0]
    assert msg['reply_parameters'] == ReplyParameters(
        message_id=888,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_notify_admin_completion_no_reply_parameters_when_admin_message_id_missing():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = None

    await service.notify_admin_completion(54321, appointment)

    msg = bot.sent_messages[0]
    assert msg['reply_parameters'] is None


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
    assert msg['reply_markup'] == appointment_reminder_details_kb(appointment.id)
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
    assert msg['reply_markup'] == appointment_reminder_details_kb(appointment.id)
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

    result = await service.notify_staff_new_booking_request(67890, appointment, "Иванов Иван")

    assert result == 777
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


@pytest.mark.asyncio
async def test_notify_client_reschedule_proposed_formats_proposed_datetime_for_display():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"

    result = await service.notify_client_reschedule_proposed(appointment)

    assert result == 777
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert "15 августа 2026, 15:00" in msg['text']
    assert "2026-08-15 15:00" not in msg['text']


@pytest.mark.asyncio
async def test_notify_client_reschedule_proposed_returns_none_when_telegram_id_missing():
    bot = FakeBot()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"

    result = await service.notify_client_reschedule_proposed(appointment)

    assert result is None
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_staff_proposal_accepted_sends_short_text():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    await service.notify_staff_proposal_accepted(54321, appointment, "Иванов Иван")

    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 54321
    assert msg['text'] == "✅ Клиент Иванов Иван согласился на предложенное время."


@pytest.mark.asyncio
async def test_notify_staff_proposal_accepted_replies_when_admin_message_id_set():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = 888

    await service.notify_staff_proposal_accepted(54321, appointment, "Иванов Иван")

    msg = bot.sent_messages[0]
    assert msg['reply_parameters'] == ReplyParameters(
        message_id=888,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_notify_staff_proposal_accepted_no_reply_parameters_when_admin_message_id_missing():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = None

    await service.notify_staff_proposal_accepted(54321, appointment, "Иванов Иван")

    msg = bot.sent_messages[0]
    assert msg['reply_parameters'] is None


@pytest.mark.asyncio
async def test_notify_staff_proposal_rejected_sends_short_text():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    await service.notify_staff_proposal_rejected(54321, appointment, "Иванов Иван")

    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 54321
    assert msg['text'] == "❌ Клиент Иванов Иван отклонил предложенное время."


@pytest.mark.asyncio
async def test_notify_staff_proposal_rejected_replies_when_admin_message_id_set():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = 888

    await service.notify_staff_proposal_rejected(54321, appointment, "Иванов Иван")

    msg = bot.sent_messages[0]
    assert msg['reply_parameters'] == ReplyParameters(
        message_id=888,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_notify_staff_proposal_rejected_no_reply_parameters_when_admin_message_id_missing():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = None

    await service.notify_staff_proposal_rejected(54321, appointment, "Иванов Иван")

    msg = bot.sent_messages[0]
    assert msg['reply_parameters'] is None


class FakeEditBot(FakeBot):
    def __init__(self, edit_exception=None):
        super().__init__()
        self.edited_messages = []
        self.edit_exception = edit_exception

    async def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        if self.edit_exception is not None:
            raise self.edit_exception

        self.edited_messages.append({
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text,
            'reply_markup': reply_markup,
        })


@pytest.mark.asyncio
async def test_notify_staff_reschedule_requested_sends_message():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"
    appointment.client_phone = "+998901234567"

    await service.notify_staff_reschedule_requested(67890, appointment, "Иванов Иван")

    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 67890
    assert "Клиент просит перенести запись" in msg['text']
    assert "Иванов Иван" in msg['text']
    assert "+998901234567" in msg['text']
    assert "10 июля 2026, 14:30" in msg['text']
    assert "15 августа 2026, 15:00" in msg['text']
    assert msg['reply_markup'] is not None


@pytest.mark.asyncio
async def test_notify_staff_reschedule_requested_falls_back_when_phone_missing():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"

    await service.notify_staff_reschedule_requested(67890, appointment, "Иванов Иван")

    msg = bot.sent_messages[0]
    assert "📱 Номер: —" in msg['text']


@pytest.mark.asyncio
async def test_notify_staff_reschedule_requested_raises_on_send_failure():
    bot = FailingBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"

    with pytest.raises(NotificationDeliveryError):
        await service.notify_staff_reschedule_requested(67890, appointment, "Иванов Иван")


@pytest.mark.asyncio
async def test_notify_client_reschedule_accepted_formats_datetime_for_display():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_reschedule_accepted(appointment)

    assert result is True
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "приняла ваш перенос" in msg['text']
    assert "10 июля 2026, 14:30" in msg['text']
    assert "2026-07-10 14:30" not in msg['text']
    assert msg['reply_parameters'] == ReplyParameters(
        message_id=555,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_notify_client_reschedule_accepted_returns_false_when_user_not_found():
    bot = FakeBot()
    user_repo = FakeUserRepo(None)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reschedule_accepted(appointment)

    assert result is False
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_reschedule_accepted_returns_false_when_telegram_id_missing():
    bot = FakeBot()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reschedule_accepted(appointment)

    assert result is False
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_reschedule_rejected_formats_datetime_for_display():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_reschedule_rejected(appointment)

    assert result is True
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "не смогла подтвердить перенос" in msg['text']
    assert "остаётся в силе" in msg['text']
    assert "10 июля 2026, 14:30" in msg['text']
    assert "2026-07-10 14:30" not in msg['text']
    assert msg['reply_parameters'] == ReplyParameters(
        message_id=555,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_notify_client_reschedule_rejected_returns_false_when_user_not_found():
    bot = FakeBot()
    user_repo = FakeUserRepo(None)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reschedule_rejected(appointment)

    assert result is False
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_reschedule_rejected_returns_false_when_telegram_id_missing():
    bot = FakeBot()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reschedule_rejected(appointment)

    assert result is False
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_reschedule_request_expired_formats_datetime_for_display():
    bot = FakeBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_reschedule_request_expired(appointment)

    assert result is True
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "не ответила на вашу заявку на перенос вовремя" in msg['text']
    assert "остаётся в силе" in msg['text']
    assert "10 июля 2026, 14:30" in msg['text']
    assert "2026-07-10 14:30" not in msg['text']
    assert msg['reply_parameters'] == ReplyParameters(
        message_id=555,
        allow_sending_without_reply=True,
    )


@pytest.mark.asyncio
async def test_notify_client_reschedule_request_expired_returns_false_when_user_not_found():
    bot = FakeBot()
    user_repo = FakeUserRepo(None)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reschedule_request_expired(appointment)

    assert result is False
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_reschedule_request_expired_returns_false_when_telegram_id_missing():
    bot = FakeBot()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reschedule_request_expired(appointment)

    assert result is False
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_close_reschedule_proposal_message_edits_message():
    bot = FakeEditBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)

    await service.close_reschedule_proposal_message(12345, 777)

    assert len(bot.edited_messages) == 1
    edited = bot.edited_messages[0]
    assert edited['chat_id'] == 12345
    assert edited['message_id'] == 777
    assert edited['text'] == "Это предложение больше не актуально."


@pytest.mark.asyncio
async def test_notify_client_appointment_details_edits_existing_message():
    bot = FakeEditBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_details(appointment)

    assert result is True
    assert len(bot.edited_messages) == 1
    edited = bot.edited_messages[0]
    assert edited['chat_id'] == 12345
    assert edited['message_id'] == 555
    assert "Вам назначена запись на прием" in edited['text']
    assert "2026-07-10 14:30" in edited['text']
    assert "Консультация" in edited['text']
    assert edited['reply_markup'] == appointment_reminder_with_buttons_kb(appointment.id)
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_details_treats_not_modified_as_success():
    bot = FakeEditBot(edit_exception=TelegramBadRequest(method=None, message="message is not modified"))
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_details(appointment)

    assert result is True
    assert len(bot.edited_messages) == 0
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_details_falls_back_to_send_message_on_other_bad_request():
    bot = FakeEditBot(edit_exception=TelegramBadRequest(method=None, message="message to edit not found"))
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_details(appointment)

    assert result is True
    assert len(bot.edited_messages) == 0
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "Вам назначена запись на прием" in msg['text']
    assert "2026-07-10 14:30" in msg['text']
    assert "Консультация" in msg['text']
    assert msg['reply_markup'] == appointment_reminder_with_buttons_kb(appointment.id)


@pytest.mark.asyncio
async def test_notify_client_appointment_details_sends_new_message_when_no_notification_message_id():
    bot = FakeEditBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = None

    result = await service.notify_client_appointment_details(appointment)

    assert result is True
    assert len(bot.edited_messages) == 0
    assert len(bot.sent_messages) == 1
    msg = bot.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "Вам назначена запись на прием" in msg['text']
    assert "2026-07-10 14:30" in msg['text']
    assert "Консультация" in msg['text']
    assert msg['reply_markup'] == appointment_reminder_with_buttons_kb(appointment.id)


@pytest.mark.asyncio
async def test_notify_client_appointment_details_returns_false_when_client_not_found():
    bot = FakeEditBot()
    user_repo = FakeUserRepo(None)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_details(appointment)

    assert result is False
    assert len(bot.edited_messages) == 0
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_details_returns_false_when_no_telegram_id():
    bot = FakeEditBot()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_details(appointment)

    assert result is False
    assert len(bot.edited_messages) == 0
    assert len(bot.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_details_includes_admin_info_when_doctor_resolves():
    bot = FakeEditBot()
    user_repo = FakeUserRepo(_client(), admin=_admin())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = None
    appointment.doctor_id = 999

    await service.notify_client_appointment_details(appointment)

    msg = bot.sent_messages[0]
    assert "Администратор: Доктор Петров" in msg['text']
    assert "+998901234568" in msg['text']


@pytest.mark.asyncio
async def test_notify_client_appointment_details_omits_admin_info_when_doctor_id_missing():
    bot = FakeEditBot()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(bot, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = None
    assert appointment.doctor_id is None

    await service.notify_client_appointment_details(appointment)

    msg = bot.sent_messages[0]
    assert "Администратор" not in msg['text']
