"""Regression coverage for stale staff decision callbacks.

The losing callback persists the exact compact result on its own notification
row, replaces that message with the compact text, and exposes Details only when
the scoped persistence succeeds.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.admin.appointment_management.appointment_completion import (
    create_admin_completion_router,
)
from bot.handlers.admin.appointment_management.booking_requests import (
    create_admin_booking_requests_router,
)
from bot.handlers.admin.appointment_management.reschedule_requests import (
    create_admin_reschedule_requests_router,
)
from bot.keyboards.admin.record_management_kb.appointment_log_details_kb import (
    appointment_log_details_kb,
)
from bot.keyboards.admin.record_management_kb.booking_request_cb import (
    BookingRequestActionCB,
)
from bot.keyboards.admin.record_management_kb.completion_followup_cb import (
    CompletionFollowupCB,
)
from bot.keyboards.admin.record_management_kb.reschedule_request_cb import (
    RescheduleRequestActionCB,
)
from bot.models.appointment import Appointment
from bot.models.appointment_notification import AppointmentNotification
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role

ADMIN_TELEGRAM_ID = 999
ADMIN_ID = 1
WINNER_ID = 55
WINNER_TELEGRAM_ID = 2000
DECIDED_LABEL = {"ru": "Администратор Ivanova Irina", "uz": "Administrator Ivanova Irina"}
NEW_PROPOSED_DATETIME = (datetime.now(timezone.utc) + timedelta(days=30)).replace(hour=12, minute=0, second=0, microsecond=0)
NEW_PROPOSED_DATETIME_DISPLAY = NEW_PROPOSED_DATETIME.strftime("%d.%m.%Y %H:%M")


class _NotificationPersistenceMixin:
    def _init_notification(self, kind, *, persistence=True):
        self.notifications = [AppointmentNotification(1, 555, 777, kind, compact_text=None)]
        self.persistence = persistence

    async def set_appointment_notification_compact_text(self, appointment_id, chat_id, message_id, kind, compact_text):
        if self.persistence is not True:
            if isinstance(self.persistence, Exception):
                raise self.persistence
            return self.persistence
        for row in self.notifications:
            if (row.appointment_id, row.chat_id, row.message_id, row.kind) == (appointment_id, chat_id, message_id, kind):
                row.compact_text = compact_text
                return True
        return False


class FakeUserRepo:
    def __init__(self):
        self.by_telegram_id = {
            ADMIN_TELEGRAM_ID: User("Petrov Petr", "+998907654321", Role.ADMIN, telegram_user_id=ADMIN_TELEGRAM_ID, ID=ADMIN_ID, clinic_id=1, clinic_name="Zub Mudrosti"),
        }
        self.by_id = {
            WINNER_ID: User("Ivanova Irina", "+998901112233", Role.ADMIN, telegram_user_id=WINNER_TELEGRAM_ID, ID=WINNER_ID, clinic_id=1, clinic_name="Zub Mudrosti"),
        }

    async def get_user_by_telegram_id(self, telegram_user_id):
        return self.by_telegram_id.get(telegram_user_id)

    async def get_user_by_id(self, user_id):
        return self.by_id.get(user_id)

    async def get_client_by_id(self, user_id):
        return None


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=1, visibility_scope="clinic", is_doctor=False)


class FakeClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=1, name="Zub Mudrosti", token="t")


def _callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.chat.id = 555
    callback_query.message.message_id = 777
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _find_handler(router, name):
    return next(handler.callback for handler in router.callback_query.handlers if handler.callback.__name__ == name)


def _admin_user(language="ru"):
    return User("Petrov Petr", "+998907654321", Role.ADMIN, telegram_user_id=ADMIN_TELEGRAM_ID, ID=ADMIN_ID, clinic_id=1, language=language)


def _notification_service():
    service = MagicMock()
    service.notifier.try_edit_message_text = AsyncMock(return_value=True)
    return service


def _assert_persisted_and_edited(repository, notification_service, *, keyboard=True, lang="ru"):
    notification_service.notifier.try_edit_message_text.assert_awaited_once()
    kwargs = notification_service.notifier.try_edit_message_text.call_args.kwargs
    assert kwargs["chat_id"] == 555
    assert kwargs["message_id"] == 777
    if keyboard:
        assert repository.notifications[0].compact_text == kwargs["text"]
    else:
        assert repository.notifications[0].compact_text is None
    assert kwargs["reply_markup"] == (appointment_log_details_kb(1, lang) if keyboard else None)
    return kwargs["text"]


@pytest.mark.asyncio
async def test_confirm_request_lost_race_persists_exact_compact_and_details_keyboard():
    class FakeAppointmentRepository(_NotificationPersistenceMixin):
        def __init__(self, appointment):
            self.appointment = appointment
            self._init_notification("booking")

        async def get_appointment_by_id(self, appointment_id): return self.appointment
        async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None): return []
        async def try_confirm_or_reject_pending(self, *args): return False

    appointment = Appointment(clinic_id=1, client_id=7, doctor_id=5, datetime="2026-08-01 10:00", purpose="Konsultatsiya", created_by=CreatedBy.CLIENT, status=AppointmentStatus.CONFIRMED, id=1, decided_by_user_id=WINNER_ID)
    repository = FakeAppointmentRepository(appointment)
    service = _notification_service()
    handler = _find_handler(create_admin_booking_requests_router("zb", repository, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(), notification_service=service), "confirm_request")
    await handler(_callback_query(), BookingRequestActionCB(action="confirm", appointment_id=1), _admin_user())
    _assert_persisted_and_edited(repository, service)


@pytest.mark.asyncio
async def test_accept_reschedule_lost_race_persists_exact_compact_and_details_keyboard():
    class FakeAppointmentRepository(_NotificationPersistenceMixin):
        def __init__(self, pre_race, post_race):
            self.current, self.post_race = pre_race, post_race
            self._init_notification("reschedule")

        async def get_appointment_by_id(self, appointment_id): return self.current
        async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None): return []
        async def try_resolve_client_reschedule(self, *args, **kwargs): self.current = self.post_race; return False

    pre = Appointment(clinic_id=1, client_id=7, doctor_id=5, datetime="2026-08-01 10:00", purpose="Konsultatsiya", created_by=CreatedBy.CLIENT, status=AppointmentStatus.CONFIRMED, id=1, proposed_datetime="2026-08-05 09:00", proposed_by=CreatedBy.CLIENT)
    post = Appointment(clinic_id=1, client_id=7, doctor_id=5, datetime="2026-08-05 09:00", purpose="Konsultatsiya", created_by=CreatedBy.CLIENT, status=AppointmentStatus.CONFIRMED, id=1, decided_by_user_id=WINNER_ID)
    repository = FakeAppointmentRepository(pre, post)
    service = _notification_service()
    handler = _find_handler(create_admin_reschedule_requests_router("zb", repository, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(), notification_service=service), "accept_reschedule")
    await handler(_callback_query(), RescheduleRequestActionCB(action="accept", appointment_id=1), _admin_user())
    _assert_persisted_and_edited(repository, service)


@pytest.mark.asyncio
@pytest.mark.parametrize("persistence", [False, RuntimeError("storage unavailable")])
async def test_booking_lost_race_clears_keyboard_when_compact_persistence_fails(persistence):
    class FakeAppointmentRepository(_NotificationPersistenceMixin):
        def __init__(self, appointment):
            self.appointment = appointment
            self._init_notification("booking", persistence=persistence)

        async def get_appointment_by_id(self, appointment_id): return self.appointment
        async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None): return []
        async def try_confirm_or_reject_pending(self, *args): return False

    repository = FakeAppointmentRepository(Appointment(clinic_id=1, client_id=7, doctor_id=5, datetime="2026-08-01 10:00", purpose="Konsultatsiya", created_by=CreatedBy.CLIENT, status=AppointmentStatus.CONFIRMED, id=1, decided_by_user_id=WINNER_ID))
    service = _notification_service()
    handler = _find_handler(create_admin_booking_requests_router("zb", repository, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(), notification_service=service), "confirm_request")
    await handler(_callback_query(), BookingRequestActionCB(action="confirm", appointment_id=1), _admin_user())
    _assert_persisted_and_edited(repository, service, keyboard=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["ru", "uz", "xx"])
async def test_completion_lost_race_uses_compact_fallback_and_exact_row(language):
    class FakeAppointmentRepository(_NotificationPersistenceMixin):
        def __init__(self, appointment):
            self.appointment = appointment
            self._init_notification("completion")

        async def get_appointment_by_id(self, appointment_id): return self.appointment
        async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None): return []
        async def try_complete_appointment(self, *args): return False

    repository = FakeAppointmentRepository(Appointment(clinic_id=1, client_id=1, doctor_id=ADMIN_ID, datetime="2026-07-10 10:00", purpose="Konsultatsiya", created_by=CreatedBy.ADMIN, status=AppointmentStatus.COMPLETED, id=1, decided_by_user_id=WINNER_ID))
    service = _notification_service()
    handler = _find_handler(create_admin_completion_router(repository, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(), notification_service=service), "skip_edit")
    await handler(_callback_query(), CompletionFollowupCB(action="skip", appointment_id=1), AsyncMock(), _admin_user(language))
    text = _assert_persisted_and_edited(repository, service, lang=language)
    if language == "xx":
        assert text == repository.notifications[0].compact_text
