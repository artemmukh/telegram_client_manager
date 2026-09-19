"""Coverage for client confirmation of a staff re-timed self-booking.

After a staff time-change the self-booking stays PENDING with status_actor=STAFF,
so the era-1 guard in confirm_appointment_by_client must let the client answer,
and confirm_invite must log the client's decision to ALL staff with kind
"reschedule" (origin-derived once origin_kind lands). Fresh self-bookings stay
blocked, admin-created invites keep the booking log, and the 2h-reminder
confirm button (appt_confirm:) never emits staff logs.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.exceptions.appointment_exceptions import AwaitingClinicDecisionError
from bot.handlers.client.appointment_invite import (
    create_client_appointment_invite_router,
)
from bot.handlers.client.appointment_response import create_client_appointment_router
from bot.keyboards.client.appointment_invite_cb import AppointmentInviteActionCB
from bot.models.appointment import Appointment
from bot.models.user import User
from bot.services.appointment.appointment_notifications import (
    DEFAULT_UNKNOWN_CLIENT_LABEL,
)
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy, StatusActor
from bot.utils.role import Role

CLINIC_ID = 1
CLIENT_ID = 7
CLIENT_NAME = "Client Clientov"
CLIENT_TELEGRAM_ID = 5000

DOCTOR_ID = 10
DOCTOR_TELEGRAM_ID = 3000

ADMIN_ID = 2
ADMIN_TELEGRAM_ID = 2000

BLOCKED_MESSAGE = {"ru": "Заявка ожидает решения клиники", "uz": "Klinika qarashini kutmoqda"}


def _doctor():
    return User(
        full_name="Sidorov Sidor", phone="+998901234567", role=Role.ADMIN,
        telegram_user_id=DOCTOR_TELEGRAM_ID, ID=DOCTOR_ID, clinic_id=CLINIC_ID,
    )


def _admin():
    return User(
        full_name="Ivanova Irina", phone="+998901112233", role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID, ID=ADMIN_ID, clinic_id=CLINIC_ID,
    )


def _client():
    return User(
        full_name=CLIENT_NAME, phone="+998900001122", role=Role.CLIENT,
        telegram_user_id=CLIENT_TELEGRAM_ID, ID=CLIENT_ID, language="ru",
    )


def _pending_appointment(created_by, status_actor):
    return Appointment(
        clinic_id=CLINIC_ID, client_id=CLIENT_ID, doctor_id=DOCTOR_ID,
        datetime="2027-08-20 09:00", purpose="Konsultatsiya",
        created_by=created_by, status=AppointmentStatus.PENDING, id=2,
        status_actor=status_actor, proposed_by=None, proposal_message_id=None,
    )


class FakeAppointmentManagement:
    def __init__(self, pre_mutation, post_mutation, confirm_error=None):
        self.pre_mutation = pre_mutation
        self.appointment = post_mutation
        self.confirm_error = confirm_error
        self.client = _client()
        self.confirm_calls = []
        self.recorded_notifications = []

    async def get_appointment_for_client(self, appointment_id, telegram_user_id):
        return self.pre_mutation

    @staticmethod
    def origin_log_kind(appointment, fallback):
        if appointment is not None and appointment.origin_kind in ("booking", "reschedule"):
            return appointment.origin_kind
        return fallback

    async def confirm_appointment_by_client(self, appointment_id, telegram_user_id):
        self.confirm_calls.append((appointment_id, telegram_user_id))
        if self.confirm_error is not None:
            raise self.confirm_error
        return self.appointment

    async def get_appointment_with_client_info(self, appointment_id):
        return self.appointment, self.client

    async def resolve_notification_recipients(self, appointment):
        return [_doctor(), _admin()]

    async def record_notification(self, appointment_id, chat_id, message_id, kind, compact_text=None):
        self.recorded_notifications.append((appointment_id, chat_id, message_id, kind, compact_text))


class FakeNotificationService:
    def __init__(self):
        self.admin_confirmation_calls = []
        self.staff_reschedule_accepted_calls = []
        self.notifier = SimpleNamespace(try_edit_message_text=AsyncMock(return_value=True))

    def _staff_delivery(self, staff_telegram_id, event):
        return SimpleNamespace(
            message_id=200000 + staff_telegram_id,
            compact_text=f"{event}:{staff_telegram_id}",
            lang="ru",
            details_available=True,
        )

    async def notify_admin_confirmation(self, staff_telegram_id, appointment, client_name):
        self.admin_confirmation_calls.append((staff_telegram_id, appointment.id, client_name))
        return self._staff_delivery(staff_telegram_id, "booking")

    async def notify_staff_reschedule_decision_accepted(self, staff_telegram_id, appointment, actor_label, client_name):
        self.staff_reschedule_accepted_calls.append(
            (staff_telegram_id, appointment.id, actor_label, client_name)
        )
        return self._staff_delivery(staff_telegram_id, "reschedule-accepted")


class FakeAppointmentScheduler:
    def __init__(self):
        self.resynced = []

    async def resync_appointment_jobs(self, appointment):
        self.resynced.append(appointment)


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _callback_query(data=None):
    callback_query = MagicMock()
    callback_query.from_user.id = CLIENT_TELEGRAM_ID
    callback_query.data = data
    callback_query.answer = AsyncMock()
    callback_query.message.message_id = 777
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _build_invite_router(appt_mng, notification_service, scheduler):
    return create_client_appointment_invite_router(appt_mng, notification_service, scheduler)


@pytest.mark.asyncio
async def test_confirm_invite_staff_retimed_self_booking_logs_reschedule_to_all_staff():
    pre_mutation = _pending_appointment(CreatedBy.CLIENT, StatusActor.STAFF)
    post_mutation = _pending_appointment(CreatedBy.CLIENT, StatusActor.CLIENT)
    post_mutation.status = AppointmentStatus.CONFIRMED
    appt_mng = FakeAppointmentManagement(pre_mutation, post_mutation)
    notification_service = FakeNotificationService()
    scheduler = FakeAppointmentScheduler()
    confirm_invite = _find_handler(
        _build_invite_router(appt_mng, notification_service, scheduler), "confirm_invite"
    )
    callback_query = _callback_query()

    await confirm_invite(
        callback_query,
        AppointmentInviteActionCB(action="confirm", appointment_id=2),
        _client(),
    )

    assert appt_mng.confirm_calls == [(2, CLIENT_TELEGRAM_ID)]
    assert scheduler.resynced == [post_mutation]
    accepted_by_telegram_id = {
        call[0]: call for call in notification_service.staff_reschedule_accepted_calls
    }
    assert set(accepted_by_telegram_id) == {DOCTOR_TELEGRAM_ID, ADMIN_TELEGRAM_ID}
    assert all(
        call[1] == 2 and call[2] is DEFAULT_UNKNOWN_CLIENT_LABEL and call[3] == CLIENT_NAME
        for call in accepted_by_telegram_id.values()
    )
    assert notification_service.admin_confirmation_calls == []
    assert {
        (row[0], row[1], row[3]) for row in appt_mng.recorded_notifications
    } == {
        (2, DOCTOR_TELEGRAM_ID, "reschedule"),
        (2, ADMIN_TELEGRAM_ID, "reschedule"),
    }


@pytest.mark.asyncio
async def test_confirm_invite_staff_retimed_self_booking_uses_persisted_origin_kind():
    # Same flow as the reschedule-kind baseline, but the persisted origin is
    # "booking" (staff re-timed a fresh self-booking): the journal kind must
    # follow the origin, not the confirm semantics.
    pre_mutation = _pending_appointment(CreatedBy.CLIENT, StatusActor.STAFF)
    pre_mutation.origin_kind = "booking"
    post_mutation = _pending_appointment(CreatedBy.CLIENT, StatusActor.CLIENT)
    post_mutation.status = AppointmentStatus.CONFIRMED
    appt_mng = FakeAppointmentManagement(pre_mutation, post_mutation)
    notification_service = FakeNotificationService()
    scheduler = FakeAppointmentScheduler()
    confirm_invite = _find_handler(
        _build_invite_router(appt_mng, notification_service, scheduler), "confirm_invite"
    )
    callback_query = _callback_query()

    await confirm_invite(
        callback_query,
        AppointmentInviteActionCB(action="confirm", appointment_id=2),
        _client(),
    )

    assert {
        (row[0], row[1], row[3]) for row in appt_mng.recorded_notifications
    } == {
        (2, DOCTOR_TELEGRAM_ID, "booking"),
        (2, ADMIN_TELEGRAM_ID, "booking"),
    }


@pytest.mark.asyncio
async def test_confirm_invite_fresh_self_booking_still_blocked():
    pre_mutation = _pending_appointment(CreatedBy.CLIENT, StatusActor.CLIENT)
    appt_mng = FakeAppointmentManagement(
        pre_mutation, pre_mutation, confirm_error=AwaitingClinicDecisionError(BLOCKED_MESSAGE)
    )
    notification_service = FakeNotificationService()
    scheduler = FakeAppointmentScheduler()
    confirm_invite = _find_handler(
        _build_invite_router(appt_mng, notification_service, scheduler), "confirm_invite"
    )
    callback_query = _callback_query()

    await confirm_invite(
        callback_query,
        AppointmentInviteActionCB(action="confirm", appointment_id=2),
        _client(),
    )

    callback_query.answer.assert_awaited_once_with(BLOCKED_MESSAGE["ru"], show_alert=True)
    callback_query.message.edit_text.assert_not_awaited()
    assert scheduler.resynced == []
    assert notification_service.admin_confirmation_calls == []
    assert notification_service.staff_reschedule_accepted_calls == []
    assert appt_mng.recorded_notifications == []


@pytest.mark.asyncio
async def test_confirm_invite_admin_created_invite_keeps_booking_log():
    pre_mutation = _pending_appointment(CreatedBy.ADMIN, StatusActor.STAFF)
    post_mutation = _pending_appointment(CreatedBy.ADMIN, StatusActor.CLIENT)
    post_mutation.status = AppointmentStatus.CONFIRMED
    appt_mng = FakeAppointmentManagement(pre_mutation, post_mutation)
    notification_service = FakeNotificationService()
    scheduler = FakeAppointmentScheduler()
    confirm_invite = _find_handler(
        _build_invite_router(appt_mng, notification_service, scheduler), "confirm_invite"
    )
    callback_query = _callback_query()

    await confirm_invite(
        callback_query,
        AppointmentInviteActionCB(action="confirm", appointment_id=2),
        _client(),
    )

    assert {call[0] for call in notification_service.admin_confirmation_calls} == {
        DOCTOR_TELEGRAM_ID, ADMIN_TELEGRAM_ID,
    }
    assert all(call[2] == CLIENT_NAME for call in notification_service.admin_confirmation_calls)
    assert notification_service.staff_reschedule_accepted_calls == []
    assert {
        (row[0], row[1], row[3]) for row in appt_mng.recorded_notifications
    } == {
        (2, DOCTOR_TELEGRAM_ID, "booking"),
        (2, ADMIN_TELEGRAM_ID, "booking"),
    }


@pytest.mark.asyncio
async def test_two_hour_reminder_confirm_emits_no_staff_log():
    pre_mutation = _pending_appointment(CreatedBy.ADMIN, StatusActor.STAFF)
    post_mutation = _pending_appointment(CreatedBy.ADMIN, StatusActor.CLIENT)
    post_mutation.status = AppointmentStatus.CONFIRMED
    appt_mng = FakeAppointmentManagement(pre_mutation, post_mutation)
    notification_service = FakeNotificationService()
    scheduler = FakeAppointmentScheduler()
    handle_appointment_confirm = _find_handler(
        create_client_appointment_router(
            SimpleNamespace(),
            appointment_management_service=appt_mng,
            notification_service=notification_service,
            appointment_scheduler=scheduler,
        ),
        "handle_appointment_confirm",
    )
    callback_query = _callback_query(data="appt_confirm:2")

    await handle_appointment_confirm(callback_query, _client())

    assert appt_mng.confirm_calls == [(2, CLIENT_TELEGRAM_ID)]
    assert scheduler.resynced == [post_mutation]
    assert notification_service.admin_confirmation_calls == []
    assert notification_service.staff_reschedule_accepted_calls == []
    assert appt_mng.recorded_notifications == []
