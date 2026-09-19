"""Coverage for staff logs after a client accepts/rejects a staff-proposed time.

Staff proposals apply immediately (proposed_by=NULL, status_actor=STAFF), so the
pre-mutation state signals a staff-origin proposal. Accepting must log the
reschedule decision to ALL staff; rejecting must reuse the client-cancel wording
(kind="cancellation"). Legacy admin proposals keep the old proposal paths.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.client.appointment_response import create_client_appointment_router
from bot.keyboards.client.appointment_manage_cb import ClientManageActionCB
from bot.models.appointment import Appointment
from bot.models.user import User
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


def _staff_origin_pending_appointment():
    return Appointment(
        clinic_id=CLINIC_ID, client_id=CLIENT_ID, doctor_id=DOCTOR_ID,
        datetime="2027-08-20 09:00", purpose="Konsultatsiya",
        created_by=CreatedBy.CLIENT, status=AppointmentStatus.PENDING, id=2,
        status_actor=StatusActor.STAFF, proposed_by=None, proposal_message_id=None,
    )


class FakeAppointmentManagement:
    def __init__(self, pre_mutation: Appointment, post_mutation: Appointment):
        self.pre_mutation = pre_mutation
        self.appointment = post_mutation
        self.client = _client()
        self.recorded_notifications = []

    async def get_appointment_for_client(self, appointment_id, telegram_user_id):
        return self.pre_mutation

    @staticmethod
    def origin_log_kind(appointment, fallback):
        if appointment is not None and appointment.origin_kind in ("booking", "reschedule"):
            return appointment.origin_kind
        return fallback

    async def accept_proposed_datetime(self, appointment_id, telegram_user_id):
        return self.appointment

    async def reject_proposed_datetime(self, appointment_id, telegram_user_id):
        return self.appointment

    async def get_appointment_with_client_info(self, appointment_id):
        return self.appointment, self.client

    async def resolve_notification_recipients(self, appointment):
        return [_doctor(), _admin()]

    async def record_notification(self, appointment_id, chat_id, message_id, kind, compact_text=None):
        self.recorded_notifications.append((appointment_id, chat_id, message_id, kind, compact_text))


class FakeNotificationService:
    def __init__(self):
        self.staff_reschedule_accepted_calls = []
        self.staff_proposal_accepted_calls = []
        self.admin_cancellation_calls = []
        self.staff_proposal_rejected_calls = []
        self.notifier = SimpleNamespace(try_edit_message_text=AsyncMock(return_value=True))

    def _staff_delivery(self, staff_telegram_id, event):
        return SimpleNamespace(
            message_id=200000 + staff_telegram_id,
            compact_text=f"{event}:{staff_telegram_id}",
            lang="ru",
            details_available=True,
        )

    async def notify_staff_reschedule_decision_accepted(self, staff_telegram_id, appointment, actor_label, client_name):
        self.staff_reschedule_accepted_calls.append((staff_telegram_id, appointment.id, actor_label, client_name))
        return self._staff_delivery(staff_telegram_id, "reschedule-accepted")

    async def notify_staff_proposal_accepted(self, staff_telegram_id, appointment, client_name):
        self.staff_proposal_accepted_calls.append((staff_telegram_id, appointment.id, client_name))
        return self._staff_delivery(staff_telegram_id, "proposal-accepted")

    async def notify_admin_cancellation(self, staff_telegram_id, appointment, client_name):
        self.admin_cancellation_calls.append((staff_telegram_id, appointment.id, client_name))
        return self._staff_delivery(staff_telegram_id, "cancellation")

    async def notify_staff_proposal_rejected(self, staff_telegram_id, appointment, client_name):
        self.staff_proposal_rejected_calls.append((staff_telegram_id, appointment.id, client_name))
        return self._staff_delivery(staff_telegram_id, "proposal-rejected")


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = CLIENT_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.message_id = 777
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _build_router(appt_mng, notification_service):
    router = create_client_appointment_router(
        SimpleNamespace(),
        appointment_management_service=appt_mng,
        notification_service=notification_service,
    )
    return router


@pytest.mark.asyncio
async def test_client_accept_staff_proposal_logs_reschedule_to_all_staff():
    pre_mutation = _staff_origin_pending_appointment()
    post_mutation = _staff_origin_pending_appointment()
    post_mutation.status = AppointmentStatus.CONFIRMED
    post_mutation.status_actor = StatusActor.CLIENT
    appt_mng = FakeAppointmentManagement(pre_mutation, post_mutation)
    notification_service = FakeNotificationService()
    manage_action = _find_handler(_build_router(appt_mng, notification_service), "manage_action")
    callback_query = _callback_query()

    await manage_action(
        callback_query,
        ClientManageActionCB(action="accept_proposal", appointment_id=2, page=1),
        MagicMock(),
        _client(),
    )

    assert {call[0] for call in notification_service.staff_reschedule_accepted_calls} == {
        DOCTOR_TELEGRAM_ID, ADMIN_TELEGRAM_ID,
    }
    assert all(call[3] == CLIENT_NAME for call in notification_service.staff_reschedule_accepted_calls)
    assert notification_service.staff_proposal_accepted_calls == []
    assert {
        (row[0], row[1], row[3]) for row in appt_mng.recorded_notifications
    } == {
        (2, DOCTOR_TELEGRAM_ID, "reschedule"),
        (2, ADMIN_TELEGRAM_ID, "reschedule"),
    }


@pytest.mark.asyncio
async def test_client_accept_staff_proposal_uses_persisted_origin_kind():
    # A staff re-time of a fresh self-booking keeps origin "booking"; the
    # journal kind must follow the persisted origin, not the accept semantics.
    pre_mutation = _staff_origin_pending_appointment()
    pre_mutation.origin_kind = "booking"
    post_mutation = _staff_origin_pending_appointment()
    post_mutation.status = AppointmentStatus.CONFIRMED
    post_mutation.status_actor = StatusActor.CLIENT
    appt_mng = FakeAppointmentManagement(pre_mutation, post_mutation)
    notification_service = FakeNotificationService()
    manage_action = _find_handler(_build_router(appt_mng, notification_service), "manage_action")
    callback_query = _callback_query()

    await manage_action(
        callback_query,
        ClientManageActionCB(action="accept_proposal", appointment_id=2, page=1),
        MagicMock(),
        _client(),
    )

    assert {
        (row[0], row[1], row[3]) for row in appt_mng.recorded_notifications
    } == {
        (2, DOCTOR_TELEGRAM_ID, "booking"),
        (2, ADMIN_TELEGRAM_ID, "booking"),
    }


@pytest.mark.asyncio
async def test_client_reject_staff_proposal_logs_cancellation_to_all_staff():
    pre_mutation = _staff_origin_pending_appointment()
    post_mutation = _staff_origin_pending_appointment()
    post_mutation.status = AppointmentStatus.CANCELLED
    post_mutation.status_actor = StatusActor.CLIENT
    appt_mng = FakeAppointmentManagement(pre_mutation, post_mutation)
    notification_service = FakeNotificationService()
    manage_action = _find_handler(_build_router(appt_mng, notification_service), "manage_action")
    callback_query = _callback_query()

    await manage_action(
        callback_query,
        ClientManageActionCB(action="reject_proposal", appointment_id=2, page=1),
        MagicMock(),
        _client(),
    )

    assert {call[0] for call in notification_service.admin_cancellation_calls} == {
        DOCTOR_TELEGRAM_ID, ADMIN_TELEGRAM_ID,
    }
    assert notification_service.staff_proposal_rejected_calls == []
    assert {
        (row[0], row[1], row[3]) for row in appt_mng.recorded_notifications
    } == {
        (2, DOCTOR_TELEGRAM_ID, "cancellation"),
        (2, ADMIN_TELEGRAM_ID, "cancellation"),
    }
