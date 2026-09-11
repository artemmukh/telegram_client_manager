from datetime import datetime, timedelta

import pytest

from bot.models.appointment import Appointment
from bot.models.appointment_notification import AppointmentNotification
from bot.models.user import User
from bot.services.appointment.appointment_decision_reminders import (
    BOOKING_DECISION_REMINDER_KIND,
)
from bot.services.appointment.appointment_jobs import (
    _send_staff_decision_reminder_with_services,
)
from bot.services.appointment.appointment_notifications import (
    AppointmentNotificationService,
)
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


class StrictNotifier:
    def __init__(self):
        self.sent = []
        self.edited = []

    async def send_message(
        self,
        chat_id,
        text,
        reply_markup=None,
        reply_to_message_id=None,
        allow_sending_without_reply=True,
    ):
        self.sent.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "reply_to_message_id": reply_to_message_id,
                "allow_sending_without_reply": allow_sending_without_reply,
            }
        )
        return 700 + len(self.sent)

    async def try_edit_message_text(self, **kwargs):
        self.edited.append(kwargs)
        return True


class ReminderUserRepository:
    async def get_user_by_telegram_id(self, telegram_id):
        return User(
            full_name="Врач",
            phone="—",
            role=Role.ADMIN,
            telegram_user_id=telegram_id,
            language="ru",
        )


class ReminderNotificationRepository:
    def __init__(self):
        self.notifications = []

    async def add_appointment_notification(
        self, appointment_id, chat_id, message_id, kind, compact_text=None
    ):
        self.notifications.append(
            {
                "appointment_id": appointment_id,
                "chat_id": chat_id,
                "message_id": message_id,
                "kind": kind,
                "compact_text": compact_text,
            }
        )


def booking_appointment(now: datetime) -> Appointment:
    return Appointment(
        id=42,
        clinic_id=1,
        client_id=7,
        datetime=(now + timedelta(days=2)).isoformat(),
        purpose="consultation",
        created_by=CreatedBy.CLIENT,
        status=AppointmentStatus.PENDING,
        created_at=now.isoformat(),
    )


@pytest.mark.asyncio
async def test_staff_decision_reminder_uses_strict_reply_and_details_log():
    notifier = StrictNotifier()
    repository = ReminderNotificationRepository()
    service = AppointmentNotificationService(
        notifier,
        ReminderUserRepository(),
        repository,
    )
    appointment = booking_appointment(datetime(2026, 9, 11, 12, 0))

    delivered = await service.notify_staff_decision_reminder(
        9001,
        appointment,
        kind=BOOKING_DECISION_REMINDER_KIND,
        reply_to_message_id=901,
    )

    assert delivered is True
    assert notifier.sent == [
        {
            "chat_id": 9001,
            "text": "⏰ Заявка №42 всё ещё ожидает решения врача.",
            "reply_markup": None,
            "reply_to_message_id": 901,
            "allow_sending_without_reply": False,
        }
    ]
    assert repository.notifications[0]["kind"] == BOOKING_DECISION_REMINDER_KIND
    assert repository.notifications[0]["compact_text"] == notifier.sent[0]["text"]
    assert len(notifier.edited) == 1


@pytest.mark.asyncio
async def test_missing_anchor_skips_reminder_without_standalone_message():
    notifier = StrictNotifier()
    repository = ReminderNotificationRepository()
    service = AppointmentNotificationService(
        notifier,
        ReminderUserRepository(),
        repository,
    )
    appointment = booking_appointment(datetime(2026, 9, 11, 12, 0))

    delivered = await service.notify_staff_decision_reminder(
        9001,
        appointment,
        kind=BOOKING_DECISION_REMINDER_KIND,
        reply_to_message_id=None,
    )

    assert delivered is False
    assert notifier.sent == []
    assert repository.notifications == []


class ReminderManagement:
    def __init__(self, targets):
        self.targets = targets

    async def get_active_notification_targets(self, appointment_id, kind):
        return self.targets


class ReminderNotificationService:
    def __init__(self):
        self.calls = []

    async def notify_staff_decision_reminder(
        self, chat_id, appointment, *, kind, reply_to_message_id
    ):
        self.calls.append((chat_id, appointment.id, kind, reply_to_message_id))
        return True


@pytest.mark.asyncio
async def test_job_replies_to_each_recipient_source_card():
    now = datetime(2026, 9, 11, 12, 0)
    appointment = booking_appointment(now)
    targets = [
        AppointmentNotification(42, 9001, 901, "booking"),
        AppointmentNotification(42, 9002, 902, "booking"),
    ]
    management = ReminderManagement(targets)
    notifications = ReminderNotificationService()

    sent_count = await _send_staff_decision_reminder_with_services(
        appointment,
        management,
        notifications,
        now,
    )

    assert sent_count == 2
    assert notifications.calls == [
        (9001, 42, BOOKING_DECISION_REMINDER_KIND, 901),
        (9002, 42, BOOKING_DECISION_REMINDER_KIND, 902),
    ]


@pytest.mark.asyncio
async def test_job_is_noop_after_deadline_even_if_scheduler_fires():
    now = datetime(2026, 9, 11, 12, 0)
    appointment = booking_appointment(now - timedelta(days=2, hours=1))
    management = ReminderManagement(
        [AppointmentNotification(42, 9001, 901, "booking")]
    )
    notifications = ReminderNotificationService()

    sent_count = await _send_staff_decision_reminder_with_services(
        appointment,
        management,
        notifications,
        now,
    )

    assert sent_count == 0
    assert notifications.calls == []


def test_origin_returns_none_when_active_targets_empty():
    from bot.services.appointment.appointment_decision_reminders import (
        BOOKING_DECISION_REMINDER_KIND,
        RESCHEDULE_DECISION_REMINDER_KIND,
        decision_reminder_origin,
    )

    now = datetime(2026, 9, 11, 12, 0)
    appointment = booking_appointment(now)

    assert decision_reminder_origin(appointment, BOOKING_DECISION_REMINDER_KIND, []) is None
    assert decision_reminder_origin(appointment, RESCHEDULE_DECISION_REMINDER_KIND, []) is None


@pytest.mark.asyncio
async def test_job_handles_recipient_delivery_error_gracefully():
    from aiogram.exceptions import TelegramBadRequest

    now = datetime(2026, 9, 11, 12, 0)
    appointment = booking_appointment(now)
    targets = [
        AppointmentNotification(42, 9001, 901, "booking"),
        AppointmentNotification(42, 9002, 902, "booking"),
    ]
    management = ReminderManagement(targets)

    class FailingNotificationService:
        def __init__(self):
            self.calls = []

        async def notify_staff_decision_reminder(
            self, chat_id, appointment, *, kind, reply_to_message_id
        ):
            self.calls.append(chat_id)
            if chat_id == 9001:
                raise TelegramBadRequest(method="send_message", message="Bad Request: message to be replied not found")
            return True

    notifications = FailingNotificationService()

    sent_count = await _send_staff_decision_reminder_with_services(
        appointment,
        management,
        notifications,
        now,
    )

    assert sent_count == 1
    assert notifications.calls == [9001, 9002]


def test_proposal_reminder_duplicate_suppression_timing():
    from bot.services.appointment.appointment_decision_reminders import (
        parse_notification_created_at,
    )

    now_tashkent = datetime(2026, 9, 11, 12, 0)
    # Decision reminder sent 5 minutes ago (UTC 06:55:00 corresponds to Tashkent 11:55:00)
    recent_notification = AppointmentNotification(
        id=1,
        appointment_id=42,
        chat_id=9001,
        message_id=555,
        kind="reschedule_decision_reminder",
        created_at="2026-09-11 06:55:00",
    )
    sent_at = parse_notification_created_at(recent_notification.created_at)
    is_duplicate = abs((now_tashkent - sent_at).total_seconds()) < 1800
    assert is_duplicate is True

    # Older reminder (2 hours ago, UTC 04:55:00 corresponds to Tashkent 09:55:00)
    older_notification = AppointmentNotification(
        id=2,
        appointment_id=42,
        chat_id=9001,
        message_id=556,
        kind="reschedule_decision_reminder",
        created_at="2026-09-11 04:55:00",
    )
    sent_at_older = parse_notification_created_at(older_notification.created_at)
    is_duplicate_older = abs((now_tashkent - sent_at_older).total_seconds()) < 1800
    assert is_duplicate_older is False


