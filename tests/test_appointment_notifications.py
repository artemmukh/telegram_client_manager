import pytest

from bot.exceptions.appointment_exceptions import NotificationDeliveryError
from bot.models.appointment import Appointment
from bot.models.user import User
from bot.keyboards.client.appointment_response_kb import (
    appointment_invite_kb,
    appointment_reminder_details_kb,
    appointment_reminder_with_buttons_kb,
    reschedule_proposal_kb,
)
from bot.services.appointment.appointment_notifications import (
    AppointmentNotificationService,
    reminder_text,
)
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy, status_label
from bot.utils.role import Role

CONFIRM_CTA = "Пожалуйста, подтвердите вашу готовность посетить запись"


class FakeTelegramNotifier:
    def __init__(self, send_exception=None, try_edit_result=True, try_edit_exception=None, edit_exception=None):
        self.sent_messages = []
        self.edited_messages = []
        self.send_exception = send_exception
        self.try_edit_result = try_edit_result
        self.try_edit_exception = try_edit_exception
        self.edit_exception = edit_exception

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None):
        if self.send_exception is not None:
            raise self.send_exception

        self.sent_messages.append({
            'chat_id': chat_id,
            'text': text,
            'reply_markup': reply_markup,
            'reply_to_message_id': reply_to_message_id,
        })

        return 777

    async def try_edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        if self.try_edit_exception is not None:
            raise self.try_edit_exception

        if self.try_edit_result:
            self.edited_messages.append({
                'chat_id': chat_id,
                'message_id': message_id,
                'text': text,
                'reply_markup': reply_markup,
            })

        return self.try_edit_result

    async def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        if self.edit_exception is not None:
            raise self.edit_exception

        self.edited_messages.append({
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text,
            'reply_markup': reply_markup,
        })


class FakeUserRepo:
    def __init__(self, user=None, admin=None, recipient_by_telegram_id=None):
        self.user = user
        self.admin = admin
        self.recipient_by_telegram_id = recipient_by_telegram_id

    async def get_client_by_id(self, client_id):
        return self.user

    async def get_user_by_id(self, user_id):
        return self.admin

    async def get_user_by_telegram_id(self, telegram_user_id):
        return self.recipient_by_telegram_id


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
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_appointment_with_buttons(appointment)

    assert result == 777
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "Вам назначена запись на прием" in msg['text']
    assert "2026-07-10 14:30" in msg['text']
    assert "Консультация" in msg['text']
    assert msg['reply_markup'] is not None


@pytest.mark.asyncio
async def test_notify_client_appointment_with_buttons_defaults_to_invite_keyboard():
    """PR3: use_invite_kb defaults to True -- a freshly created admin invite
    (PENDING+ADMIN, not yet answered) gets the 3-button appointment_invite_kb
    (Confirm / Propose different time / Cancel)."""
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_appointment_with_buttons(appointment)

    assert result == 777
    msg = notifier.sent_messages[0]
    assert msg['reply_markup'] == appointment_invite_kb(appointment.id)


@pytest.mark.asyncio
async def test_notify_client_appointment_with_buttons_use_invite_kb_false_uses_details_keyboard():
    """PR3: use_invite_kb=False is for the case where the appointment is already
    CONFIRMED (e.g. the clinic just approved a client self-booking request) -- no
    decision is pending, so the client sees no negotiation buttons, just
    appointment_reminder_details_kb."""
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.status = AppointmentStatus.CONFIRMED

    result = await service.notify_client_appointment_with_buttons(appointment, use_invite_kb=False)

    assert result == 777
    msg = notifier.sent_messages[0]
    assert msg['reply_markup'] == appointment_reminder_details_kb(appointment.id)
    assert msg['reply_markup'] != appointment_invite_kb(appointment.id)


@pytest.mark.asyncio
async def test_notify_client_appointment_returns_false_when_user_not_found():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(None)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_appointment_with_buttons(appointment)

    assert result is None
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_returns_false_when_telegram_id_missing():
    notifier = FakeTelegramNotifier()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_appointment_with_buttons(appointment)

    assert result is None
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_admin_cancellation():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    await service.notify_admin_cancellation(54321, appointment, "Иванов Иван")

    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 54321
    assert msg['text'] == "Клиент Иванов Иван отменил запись."


@pytest.mark.asyncio
async def test_notify_admin_cancellation_replies_when_admin_message_id_set():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = 888

    await service.notify_admin_cancellation(54321, appointment, "Иванов Иван")

    msg = notifier.sent_messages[0]
    assert msg['reply_to_message_id'] == 888


@pytest.mark.asyncio
async def test_notify_admin_cancellation_no_reply_parameters_when_admin_message_id_missing():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = None

    await service.notify_admin_cancellation(54321, appointment, "Иванов Иван")

    msg = notifier.sent_messages[0]
    assert msg['reply_to_message_id'] is None


@pytest.mark.asyncio
async def test_notify_admin_confirmation_sends_short_text():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    await service.notify_admin_confirmation(54321, appointment, "Иванов Иван")

    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 54321
    assert msg['text'] == "Клиент Иванов Иван подтвердил запись."


@pytest.mark.asyncio
async def test_notify_admin_confirmation_replies_when_admin_message_id_set():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = 888

    await service.notify_admin_confirmation(54321, appointment, "Иванов Иван")

    msg = notifier.sent_messages[0]
    assert msg['reply_to_message_id'] == 888


@pytest.mark.asyncio
async def test_notify_admin_confirmation_no_reply_parameters_when_admin_message_id_missing():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = None

    await service.notify_admin_confirmation(54321, appointment, "Иванов Иван")

    msg = notifier.sent_messages[0]
    assert msg['reply_to_message_id'] is None


@pytest.mark.asyncio
async def test_notify_admin_completion_sends_followup_prompt_with_keyboard():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    await service.notify_admin_completion(54321, appointment)

    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 54321
    assert msg['text'] == (
        "Приём отмечен как завершённый. Открыть запись для правок (статус/услуга/цена)?"
    )
    assert msg['reply_markup'] is not None


@pytest.mark.asyncio
async def test_notify_admin_completion_replies_when_admin_message_id_set():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = 888

    await service.notify_admin_completion(54321, appointment)

    msg = notifier.sent_messages[0]
    assert msg['reply_to_message_id'] == 888


@pytest.mark.asyncio
async def test_notify_admin_completion_no_reply_parameters_when_admin_message_id_missing():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = None

    await service.notify_admin_completion(54321, appointment)

    msg = notifier.sent_messages[0]
    assert msg['reply_to_message_id'] is None


@pytest.mark.asyncio
async def test_notify_client_reminder_without_buttons_replies_when_message_id_set():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_reminder_without_buttons(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert msg['text'] == reminder_text("ru")
    assert msg['reply_markup'] == appointment_reminder_details_kb(appointment.id)
    assert msg['reply_to_message_id'] == 555


@pytest.mark.asyncio
async def test_notify_client_reminder_without_buttons_no_reply_parameters_when_message_id_missing():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = None

    result = await service.notify_client_reminder_without_buttons(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['text'] == reminder_text("ru")
    assert msg['reply_markup'] == appointment_reminder_details_kb(appointment.id)
    assert msg['reply_to_message_id'] is None


@pytest.mark.asyncio
async def test_notify_client_reminder_without_buttons_returns_false_when_no_telegram_id():
    notifier = FakeTelegramNotifier()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reminder_without_buttons(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_reminder_with_buttons_replies_when_message_id_set():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_reminder_with_buttons(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert msg['text'] == reminder_text("ru")
    assert msg['reply_markup'] == appointment_reminder_with_buttons_kb(appointment.id)
    assert msg['reply_to_message_id'] == 555


@pytest.mark.asyncio
async def test_notify_client_reminder_with_buttons_no_reply_parameters_when_message_id_missing():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = None

    result = await service.notify_client_reminder_with_buttons(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['text'] == reminder_text("ru")
    assert msg['reply_markup'] is not None
    assert msg['reply_to_message_id'] is None


@pytest.mark.asyncio
async def test_notify_client_reminder_with_buttons_returns_false_when_no_telegram_id():
    notifier = FakeTelegramNotifier()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reminder_with_buttons(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_cancelled_by_admin_replies_when_message_id_set():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_cancelled_by_admin(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "отменена администратором" in msg['text']
    assert msg['reply_markup'] is None
    assert msg['reply_to_message_id'] == 555


@pytest.mark.asyncio
async def test_notify_client_appointment_cancelled_by_admin_no_reply_parameters_when_message_id_missing():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = None

    result = await service.notify_client_appointment_cancelled_by_admin(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "отменена администратором" in msg['text']
    assert msg['reply_markup'] is None
    assert msg['reply_to_message_id'] is None


@pytest.mark.asyncio
async def test_notify_client_appointment_cancelled_by_admin_returns_false_when_no_telegram_id():
    notifier = FakeTelegramNotifier()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_appointment_cancelled_by_admin(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_changed_sends_updated_details():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_changed(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "изменены администратором" in msg['text']
    assert "2026-07-10 14:30" in msg['text']
    assert "Консультация" in msg['text']
    assert msg['reply_markup'] is None
    assert msg['reply_to_message_id'] == 555


@pytest.mark.asyncio
async def test_notify_client_appointment_changed_no_reply_parameters_when_message_id_missing():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = None

    result = await service.notify_client_appointment_changed(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "изменены администратором" in msg['text']
    assert "2026-07-10 14:30" in msg['text']
    assert "Консультация" in msg['text']
    assert msg['reply_markup'] is None
    assert msg['reply_to_message_id'] is None


@pytest.mark.asyncio
async def test_notify_client_appointment_changed_returns_false_when_no_telegram_id():
    notifier = FakeTelegramNotifier()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_appointment_changed(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_staff_new_booking_request_sends_message():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_staff_new_booking_request(67890, appointment, "Иванов Иван")

    assert result == 777
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 67890
    assert "Новая заявка на запись" in msg['text']
    assert "Иванов Иван" in msg['text']
    assert "2026-07-10 14:30" in msg['text']
    assert "Консультация" in msg['text']


@pytest.mark.asyncio
async def test_notify_staff_new_booking_request_raises_on_send_failure():
    notifier = FakeTelegramNotifier(send_exception=RuntimeError("Telegram API error"))
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    with pytest.raises(NotificationDeliveryError):
        await service.notify_staff_new_booking_request(67890, appointment, "Иванов Иван")


@pytest.mark.asyncio
async def test_notify_client_pending_request_expired_sends_message():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_pending_request_expired(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "истекла" in msg['text']


@pytest.mark.asyncio
async def test_notify_client_pending_request_expired_uses_neutral_wording_when_proposal_outstanding():
    """When proposed_datetime is set, the wording must stay neutral about which
    side missed the deadline -- it now covers both the clinic-proposed case and
    the new case where the client proposed a time on an admin-created invite and
    the admin never answered."""
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"

    result = await service.notify_client_pending_request_expired(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['text'] == "⌛ Предложение по времени записи осталось без ответа, заявка на запись истекла."


@pytest.mark.asyncio
async def test_notify_client_pending_request_expired_returns_false_when_user_not_found():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(None)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_pending_request_expired(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_pending_request_expired_returns_false_when_telegram_id_missing():
    notifier = FakeTelegramNotifier()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_pending_request_expired(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_reschedule_proposed_formats_proposed_datetime_for_display():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"

    result = await service.notify_client_reschedule_proposed(appointment)

    assert result == 777
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert "15 августа 2026, 15:00" in msg['text']
    assert "2026-08-15 15:00" not in msg['text']


@pytest.mark.asyncio
async def test_notify_client_reschedule_proposed_returns_none_when_telegram_id_missing():
    notifier = FakeTelegramNotifier()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"

    result = await service.notify_client_reschedule_proposed(appointment)

    assert result is None
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_reschedule_proposed_formats_proposed_datetime_for_display():
    """PR2 Part 2: distinct from notify_client_reschedule_proposed (used for the
    self-booking PENDING flow), this notifies the client that the clinic wants
    to move an already-CONFIRMED appointment. Uses the same reschedule_proposal_kb
    (accept/reject) since the response flow is identical."""
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.status = AppointmentStatus.CONFIRMED
    appointment.proposed_datetime = "2026-08-15 15:00"

    result = await service.notify_client_appointment_reschedule_proposed(appointment)

    assert result == 777
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert msg['reply_markup'] == reschedule_proposal_kb(appointment.id)
    assert "перенести вашу запись" in msg['text']
    assert "15 августа 2026, 15:00" in msg['text']
    assert "2026-08-15 15:00" not in msg['text']


@pytest.mark.asyncio
async def test_notify_client_appointment_reschedule_proposed_shows_current_and_proposed_time():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.status = AppointmentStatus.CONFIRMED
    appointment.proposed_datetime = "2026-08-15 15:00"

    await service.notify_client_appointment_reschedule_proposed(appointment)

    msg = notifier.sent_messages[0]
    assert "10 июля 2026, 14:30" in msg['text']
    assert "15 августа 2026, 15:00" in msg['text']
    assert "2026-07-10 14:30" not in msg['text']
    assert "2026-08-15 15:00" not in msg['text']


@pytest.mark.asyncio
async def test_notify_client_appointment_reschedule_proposed_returns_none_when_client_missing():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(None)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.status = AppointmentStatus.CONFIRMED
    appointment.proposed_datetime = "2026-08-15 15:00"

    result = await service.notify_client_appointment_reschedule_proposed(appointment)

    assert result is None
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_reschedule_proposed_returns_none_when_telegram_id_missing():
    notifier = FakeTelegramNotifier()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.status = AppointmentStatus.CONFIRMED
    appointment.proposed_datetime = "2026-08-15 15:00"

    result = await service.notify_client_appointment_reschedule_proposed(appointment)

    assert result is None
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_staff_proposal_accepted_sends_short_text():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    await service.notify_staff_proposal_accepted(54321, appointment, "Иванов Иван")

    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 54321
    assert msg['text'] == "✅ Клиент Иванов Иван согласился на предложенное время."


@pytest.mark.asyncio
async def test_notify_staff_proposal_accepted_replies_when_admin_message_id_set():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = 888

    await service.notify_staff_proposal_accepted(54321, appointment, "Иванов Иван")

    msg = notifier.sent_messages[0]
    assert msg['reply_to_message_id'] == 888


@pytest.mark.asyncio
async def test_notify_staff_proposal_accepted_no_reply_parameters_when_admin_message_id_missing():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = None

    await service.notify_staff_proposal_accepted(54321, appointment, "Иванов Иван")

    msg = notifier.sent_messages[0]
    assert msg['reply_to_message_id'] is None


@pytest.mark.asyncio
async def test_notify_staff_proposal_rejected_sends_short_text():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    await service.notify_staff_proposal_rejected(54321, appointment, "Иванов Иван")

    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 54321
    assert msg['text'] == "❌ Клиент Иванов Иван отклонил предложенное время."


@pytest.mark.asyncio
async def test_notify_staff_proposal_rejected_replies_when_admin_message_id_set():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = 888

    await service.notify_staff_proposal_rejected(54321, appointment, "Иванов Иван")

    msg = notifier.sent_messages[0]
    assert msg['reply_to_message_id'] == 888


@pytest.mark.asyncio
async def test_notify_staff_proposal_rejected_no_reply_parameters_when_admin_message_id_missing():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = None

    await service.notify_staff_proposal_rejected(54321, appointment, "Иванов Иван")

    msg = notifier.sent_messages[0]
    assert msg['reply_to_message_id'] is None


@pytest.mark.asyncio
async def test_notify_staff_reschedule_requested_sends_message():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"
    appointment.client_phone = "+998901234567"

    await service.notify_staff_reschedule_requested(67890, appointment, "Иванов Иван")

    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 67890
    assert "Клиент просит перенести запись" in msg['text']
    assert "Иванов Иван" in msg['text']
    assert "+998901234567" in msg['text']
    assert "10 июля 2026, 14:30" in msg['text']
    assert "15 августа 2026, 15:00" in msg['text']
    assert msg['reply_markup'] is not None


@pytest.mark.asyncio
async def test_notify_staff_reschedule_requested_falls_back_when_phone_missing():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"

    await service.notify_staff_reschedule_requested(67890, appointment, "Иванов Иван")

    msg = notifier.sent_messages[0]
    assert "📱 Номер: —" in msg['text']


@pytest.mark.asyncio
async def test_notify_staff_reschedule_requested_raises_on_send_failure():
    notifier = FakeTelegramNotifier(send_exception=RuntimeError("Telegram API error"))
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"

    with pytest.raises(NotificationDeliveryError):
        await service.notify_staff_reschedule_requested(67890, appointment, "Иванов Иван")


@pytest.mark.asyncio
async def test_notify_client_reschedule_accepted_formats_datetime_for_display():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_reschedule_accepted(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "приняла ваш перенос" in msg['text']
    assert "10 июля 2026, 14:30" in msg['text']
    assert "2026-07-10 14:30" not in msg['text']
    assert msg['reply_to_message_id'] == 555


@pytest.mark.asyncio
async def test_notify_client_reschedule_accepted_returns_false_when_user_not_found():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(None)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reschedule_accepted(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_reschedule_accepted_returns_false_when_telegram_id_missing():
    notifier = FakeTelegramNotifier()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reschedule_accepted(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_reschedule_rejected_states_appointment_cancelled():
    """Rejecting a client's reschedule request is terminal (PR2): the message
    must say the appointment was cancelled, not that it remains in force."""
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_reschedule_rejected(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "не смогла подтвердить перенос" in msg['text']
    assert "запись отменена" in msg['text']
    assert "остаётся в силе" not in msg['text']
    assert msg['reply_to_message_id'] == 555


@pytest.mark.asyncio
async def test_notify_client_reschedule_rejected_returns_false_when_user_not_found():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(None)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reschedule_rejected(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_reschedule_rejected_returns_false_when_telegram_id_missing():
    notifier = FakeTelegramNotifier()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reschedule_rejected(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_reschedule_request_expired_formats_datetime_for_display():
    """PR2 makes the wording neutral about which side missed the deadline
    (the job now applies to both client- and admin-initiated proposals),
    so the text no longer blames the clinic specifically."""
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_reschedule_request_expired(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "истекло без ответа" in msg['text']
    assert "не ответила на вашу заявку на перенос вовремя" not in msg['text']
    assert "остаётся в силе" in msg['text']
    assert "10 июля 2026, 14:30" in msg['text']
    assert "2026-07-10 14:30" not in msg['text']
    assert msg['reply_to_message_id'] == 555


@pytest.mark.asyncio
async def test_notify_client_reschedule_request_expired_returns_false_when_user_not_found():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(None)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reschedule_request_expired(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_reschedule_request_expired_returns_false_when_telegram_id_missing():
    notifier = FakeTelegramNotifier()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    result = await service.notify_client_reschedule_request_expired(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_reschedule_reminder_shows_current_and_proposed_time():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.status = AppointmentStatus.CONFIRMED
    appointment.proposed_datetime = "2026-08-15 15:00"

    result = await service.notify_client_appointment_reschedule_reminder(appointment)

    assert result is True
    msg = notifier.sent_messages[0]
    assert "10 июля 2026, 14:30" in msg['text']
    assert "15 августа 2026, 15:00" in msg['text']
    assert "2026-07-10 14:30" not in msg['text']
    assert "2026-08-15 15:00" not in msg['text']


@pytest.mark.asyncio
async def test_notify_client_appointment_reschedule_reminder_replies_to_proposal_message():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.status = AppointmentStatus.CONFIRMED
    appointment.proposed_datetime = "2026-08-15 15:00"
    appointment.proposal_message_id = 555

    await service.notify_client_appointment_reschedule_reminder(appointment)

    msg = notifier.sent_messages[0]
    assert msg['reply_to_message_id'] == 555


@pytest.mark.asyncio
async def test_notify_client_appointment_reschedule_reminder_returns_false_when_telegram_id_missing():
    notifier = FakeTelegramNotifier()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.status = AppointmentStatus.CONFIRMED
    appointment.proposed_datetime = "2026-08-15 15:00"

    result = await service.notify_client_appointment_reschedule_reminder(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_staff_reschedule_requested_shows_both_times_regression():
    """Regression test only -- notify_staff_reschedule_requested already showed
    both current and proposed time before this task; this task must not change it."""
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"
    appointment.client_phone = "+998901234567"

    await service.notify_staff_reschedule_requested(67890, appointment, "Иванов Иван")

    msg = notifier.sent_messages[0]
    assert "Текущее время: 10 июля 2026, 14:30" in msg['text']
    assert "Предложенное время: 15 августа 2026, 15:00" in msg['text']


@pytest.mark.asyncio
async def test_close_reschedule_proposal_message_edits_message():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)

    await service.close_reschedule_proposal_message(12345, 777)

    assert len(notifier.edited_messages) == 1
    edited = notifier.edited_messages[0]
    assert edited['chat_id'] == 12345
    assert edited['message_id'] == 777
    assert edited['text'] == "Это предложение больше не актуально."


@pytest.mark.asyncio
async def test_invalidate_stale_decision_message_edits_message():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)

    await service.invalidate_stale_decision_message(
        12345, 777,
        {"ru": "Доктор Петров", "uz": "Shifokor Петров"},
        {"ru": "подтверждена", "uz": "tasdiqlandi"},
    )

    assert len(notifier.edited_messages) == 1
    edited = notifier.edited_messages[0]
    assert edited['chat_id'] == 12345
    assert edited['message_id'] == 777
    assert edited['text'] == "Доктор Петров уже принял(а) решение: подтверждена."
    assert edited['reply_markup'] is None


@pytest.mark.asyncio
async def test_invalidate_stale_decision_message_swallows_telegram_bad_request():
    """The recipient's message may already be deleted/inaccessible by the time
    a sibling notification gets invalidated -- this must never blow up the
    invalidation loop across the rest of the recipients."""
    notifier = FakeTelegramNotifier(try_edit_result=False)
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)

    await service.invalidate_stale_decision_message(
        12345, 777,
        {"ru": "Доктор Петров", "uz": "Shifokor Петров"},
        {"ru": "подтверждена", "uz": "tasdiqlandi"},
    )

    assert len(notifier.edited_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_details_edits_existing_message():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_details(appointment)

    assert result is True
    assert len(notifier.edited_messages) == 1
    edited = notifier.edited_messages[0]
    assert edited['chat_id'] == 12345
    assert edited['message_id'] == 555
    assert "Вам назначена запись на прием" in edited['text']
    assert "2026-07-10 14:30" in edited['text']
    assert "Консультация" in edited['text']
    assert edited['reply_markup'] == appointment_invite_kb(appointment.id)
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_details_treats_not_modified_as_success():
    """TelegramNotifier.try_edit_message_text already special-cases "message is not
    modified" as a successful edit (returns True) before this service ever sees it,
    so from here this is indistinguishable from a plain successful edit -- no fallback
    send, and the edit is recorded same as any other successful edit."""
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_details(appointment)

    assert result is True
    assert len(notifier.edited_messages) == 1
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_details_falls_back_to_send_message_on_other_bad_request():
    notifier = FakeTelegramNotifier(try_edit_result=False)
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_details(appointment)

    assert result is True
    assert len(notifier.edited_messages) == 0
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "Вам назначена запись на прием" in msg['text']
    assert "2026-07-10 14:30" in msg['text']
    assert "Консультация" in msg['text']
    assert msg['reply_markup'] == appointment_invite_kb(appointment.id)


@pytest.mark.asyncio
async def test_notify_client_appointment_details_sends_new_message_when_no_notification_message_id():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = None

    result = await service.notify_client_appointment_details(appointment)

    assert result is True
    assert len(notifier.edited_messages) == 0
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert "Вам назначена запись на прием" in msg['text']
    assert "2026-07-10 14:30" in msg['text']
    assert "Консультация" in msg['text']
    assert msg['reply_markup'] == appointment_invite_kb(appointment.id)


@pytest.mark.asyncio
async def test_notify_client_appointment_details_returns_false_when_client_not_found():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(None)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_details(appointment)

    assert result is False
    assert len(notifier.edited_messages) == 0
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_details_returns_false_when_no_telegram_id():
    notifier = FakeTelegramNotifier()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_details(appointment)

    assert result is False
    assert len(notifier.edited_messages) == 0
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_client_appointment_details_includes_admin_info_when_doctor_resolves():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client(), admin=_admin())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = None
    appointment.doctor_id = 999

    await service.notify_client_appointment_details(appointment)

    msg = notifier.sent_messages[0]
    assert "Администратор: Доктор Петров" in msg['text']
    assert "+998901234568" in msg['text']


@pytest.mark.asyncio
async def test_notify_client_appointment_details_omits_admin_info_when_doctor_id_missing():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.notification_message_id = None
    assert appointment.doctor_id is None

    await service.notify_client_appointment_details(appointment)

    msg = notifier.sent_messages[0]
    assert "Администратор" not in msg['text']


@pytest.mark.asyncio
async def test_build_appointment_message_pending_shows_confirm_cta():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    assert appointment.status == AppointmentStatus.PENDING

    text = service._build_appointment_message(appointment)

    assert text.splitlines()[-1] == CONFIRM_CTA
    assert "Статус:" not in text


@pytest.mark.asyncio
async def test_build_appointment_message_confirmed_shows_status_label_instead_of_cta():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.status = AppointmentStatus.CONFIRMED

    text = service._build_appointment_message(appointment)

    expected_label = status_label(AppointmentStatus.CONFIRMED)
    assert text.splitlines()[-1] == f"Статус: {expected_label}"
    assert CONFIRM_CTA not in text


@pytest.mark.asyncio
async def test_build_appointment_message_confirmed_with_proposal_shows_line_and_note():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.status = AppointmentStatus.CONFIRMED
    appointment.proposed_datetime = "2026-08-15 15:00"
    appointment.proposed_by = CreatedBy.ADMIN

    text = service._build_appointment_message(appointment)

    assert "Клиника предложила перенос на: 15 августа 2026, 15:00" in text
    assert "ℹ️ Ответить на предложение можно в уведомлении о переносе." in text


@pytest.mark.asyncio
async def test_build_appointment_message_pending_with_proposal_omits_negotiation_note():
    """The PENDING branch already has its own correct wording (CONFIRM_CTA) --
    the negotiation line/note is only for CONFIRMED+proposed."""
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    assert appointment.status == AppointmentStatus.PENDING
    appointment.proposed_datetime = "2026-08-15 15:00"
    appointment.proposed_by = CreatedBy.ADMIN

    text = service._build_appointment_message(appointment)

    assert text.splitlines()[-1] == CONFIRM_CTA
    assert "предложила перенос" not in text
    assert "ℹ️ Ответить на предложение можно в уведомлении о переносе." not in text


@pytest.mark.asyncio
async def test_build_appointment_message_cancelled_shows_status_label_instead_of_cta():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.status = AppointmentStatus.CANCELLED

    text = service._build_appointment_message(appointment)

    expected_label = status_label(AppointmentStatus.CANCELLED)
    assert text.splitlines()[-1] == f"Статус: {expected_label}"
    assert CONFIRM_CTA not in text


@pytest.mark.asyncio
async def test_notify_client_appointment_details_uses_confirm_buttons_keyboard_for_pending():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    assert appointment.status == AppointmentStatus.PENDING
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_details(appointment)

    assert result is True
    edited = notifier.edited_messages[0]
    assert edited['reply_markup'] == appointment_invite_kb(appointment.id)


@pytest.mark.asyncio
async def test_notify_client_appointment_details_uses_details_only_keyboard_for_confirmed():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.status = AppointmentStatus.CONFIRMED
    appointment.notification_message_id = 555

    result = await service.notify_client_appointment_details(appointment)

    assert result is True
    assert len(notifier.edited_messages) == 1
    edited = notifier.edited_messages[0]
    assert edited['chat_id'] == 12345
    assert edited['message_id'] == 555
    assert edited['reply_markup'] == appointment_reminder_details_kb(appointment.id)
    assert edited['reply_markup'] != appointment_invite_kb(appointment.id)
    assert f"Статус: {status_label(AppointmentStatus.CONFIRMED)}" in edited['text']


@pytest.mark.asyncio
async def test_notify_client_proposal_reminder_replies_to_proposal_message_not_notification_message():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"
    appointment.proposal_message_id = 555
    appointment.notification_message_id = 999

    result = await service.notify_client_proposal_reminder(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 12345
    assert msg['reply_markup'] is None
    assert msg['reply_to_message_id'] == 555
    assert "15 августа 2026, 15:00" in msg['text']


@pytest.mark.asyncio
async def test_notify_client_proposal_reminder_no_reply_parameters_when_proposal_message_id_missing():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"
    appointment.proposal_message_id = None

    result = await service.notify_client_proposal_reminder(appointment)

    assert result is True
    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['reply_to_message_id'] is None


@pytest.mark.asyncio
async def test_notify_client_proposal_reminder_returns_false_when_user_not_found():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(None)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"

    result = await service.notify_client_proposal_reminder(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0


@pytest.mark.asyncio
async def test_notify_admin_proposal_reminder_sends_to_given_telegram_id():
    """notify_admin_proposal_reminder(telegram_id, appointment) sends directly to
    whatever telegram_id it's called with -- it no longer resolves or gates on
    appointment.created_by_telegram_id at all (that internal single-recipient
    guard was removed as part of the resolve_notification_recipients fan-out)."""
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    await service.notify_admin_proposal_reminder(54321, appointment)

    assert len(notifier.sent_messages) == 1
    msg = notifier.sent_messages[0]
    assert msg['chat_id'] == 54321
    assert msg['text'] == "⏰ Клиент предложил другое время, ответ ещё не получен."


@pytest.mark.asyncio
async def test_notify_admin_proposal_reminder_ignores_created_by_telegram_id():
    """Proves the old internal guard is really gone: even when
    created_by_telegram_id is set to a DIFFERENT value than the telegram_id the
    method is called with, the message still goes to the passed-in telegram_id,
    not to created_by_telegram_id."""
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()

    await service.notify_admin_proposal_reminder(54321, appointment)

    assert len(notifier.sent_messages) == 1
    assert notifier.sent_messages[0]['chat_id'] == 54321


@pytest.mark.asyncio
async def test_notify_admin_proposal_reminder_replies_when_admin_message_id_set():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = 888

    await service.notify_admin_proposal_reminder(54321, appointment)

    msg = notifier.sent_messages[0]
    assert msg['reply_to_message_id'] == 888


@pytest.mark.asyncio
async def test_notify_admin_proposal_reminder_no_reply_parameters_when_admin_message_id_missing():
    notifier = FakeTelegramNotifier()
    user_repo = FakeUserRepo(_client())
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.admin_notification_message_id = None

    await service.notify_admin_proposal_reminder(54321, appointment)

    msg = notifier.sent_messages[0]
    assert msg['reply_to_message_id'] is None


@pytest.mark.asyncio
async def test_notify_client_proposal_reminder_returns_false_when_telegram_id_missing():
    notifier = FakeTelegramNotifier()
    client = _client()
    client.telegram_user_id = None
    user_repo = FakeUserRepo(client)
    appointment_repo = FakeAppointmentRepo()

    service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    appointment = _appointment()
    appointment.proposed_datetime = "2026-08-15 15:00"

    result = await service.notify_client_proposal_reminder(appointment)

    assert result is False
    assert len(notifier.sent_messages) == 0
