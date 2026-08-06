"""Coverage for the staff-notification fan-out added to booking_requests.py and
reschedule_requests.py: once one staff member (doctor or clinic admin) decides
a client's booking/reschedule request, the rest of the clinic's staff (the
treating doctor plus every other clinic-scope admin) must be notified of the
outcome via notification_service.notify_staff_booking_confirmed/rejected or
notify_staff_reschedule_decision_accepted/rejected -- the acting admin must
never notify themselves. Also covers the sibling-invalidation path
(invalidate_sibling_notifications), which now builds and passes an
appointment_summary card to invalidate_stale_decision_message.

Also covers the appointment_browser.py/appointment_creation.py staff fan-out
that now goes through the consolidated notify_staff_appointment_cancellation/
notify_staff_appointment_creation helpers in appointment_decision_helpers.py:
- creation (finish()): the acting admin is excluded from the fan-out.
- cancellation (set_status -> CANCELLED): notified with the "cancelled"
  wording and recorded in appointment_notifications (the row survives).
- deletion (finish_delete): notified with the "deleted" wording, NOT recorded
  (the row is gone), and only AFTER delete_appointment succeeds -- if the
  delete fails, no notification must be sent at all.

Follows the direct-callback-invocation pattern established in
test_booking_requests_ownership.py / test_appointment_decision_conflicts.py.
"""
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.admin.appointment_management.appointment_browser import (
    create_admin_appointment_browser_router,
)
from bot.handlers.admin.appointment_management.appointment_creation import (
    create_admin_appointment_creation_router,
)
from bot.handlers.admin.appointment_management.booking_requests import (
    create_admin_booking_requests_router,
)
from bot.handlers.utils.admin_utils.appointment_helpers import build_appointment_card
from bot.handlers.admin.appointment_management.reschedule_requests import (
    create_admin_reschedule_requests_router,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import ApptActionCB
from bot.keyboards.admin.record_management_kb.booking_request_cb import BookingRequestActionCB
from bot.keyboards.admin.record_management_kb.reschedule_request_cb import RescheduleRequestActionCB
from bot.models.appointment import Appointment
from bot.models.appointment_notification import AppointmentNotification
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


CLINIC_ID = 1
CLIENT_ID = 7
CLIENT_NAME = "Client Clientov"

DOCTOR_ID = 10
DOCTOR_TELEGRAM_ID = 3000

ACTOR_ADMIN_ID = 1
ACTOR_ADMIN_TELEGRAM_ID = 999

OTHER_ADMIN_ID = 2
OTHER_ADMIN_TELEGRAM_ID = 2000

ACTOR_LABEL = {"ru": "Администратор Petrov Petr", "uz": "Administrator Petrov Petr"}


def _doctor():
    return User(
        full_name="Sidorov Sidor", phone="+998901234567", role=Role.ADMIN,
        telegram_user_id=DOCTOR_TELEGRAM_ID, ID=DOCTOR_ID, clinic_id=CLINIC_ID, clinic_name="Zub Mudrosti",
    )


def _actor_admin():
    return User(
        full_name="Petrov Petr", phone="+998907654321", role=Role.ADMIN,
        telegram_user_id=ACTOR_ADMIN_TELEGRAM_ID, ID=ACTOR_ADMIN_ID, clinic_id=CLINIC_ID, clinic_name="Zub Mudrosti",
    )


def _other_admin():
    return User(
        full_name="Ivanova Irina", phone="+998901112233", role=Role.ADMIN,
        telegram_user_id=OTHER_ADMIN_TELEGRAM_ID, ID=OTHER_ADMIN_ID, clinic_id=CLINIC_ID, clinic_name="Zub Mudrosti",
    )


def _client(telegram_user_id=None):
    return User(
        full_name=CLIENT_NAME, phone="+998900001122", role=Role.CLIENT,
        telegram_user_id=telegram_user_id, ID=CLIENT_ID,
    )


class FakeUserRepo:
    def __init__(self, client):
        self.by_telegram_id = {
            DOCTOR_TELEGRAM_ID: _doctor(),
            ACTOR_ADMIN_TELEGRAM_ID: _actor_admin(),
            OTHER_ADMIN_TELEGRAM_ID: _other_admin(),
        }
        self.by_id = {
            DOCTOR_ID: _doctor(),
            ACTOR_ADMIN_ID: _actor_admin(),
            OTHER_ADMIN_ID: _other_admin(),
        }
        self.client = client

    async def get_user_by_telegram_id(self, telegram_user_id):
        return self.by_telegram_id.get(telegram_user_id)

    async def get_user_by_id(self, user_id):
        return self.by_id.get(user_id)

    async def get_client_by_id(self, user_id):
        return self.client if self.client and self.client.ID == user_id else None

    async def get_client_by_phone(self, phone):
        return self.client if self.client and self.client.phone == phone else None


class FakeStaffRepo:
    def __init__(self):
        self.by_telegram_id = {
            DOCTOR_TELEGRAM_ID: Staff(telegram_user_id=DOCTOR_TELEGRAM_ID, clinic_id=CLINIC_ID, visibility_scope="own"),
            ACTOR_ADMIN_TELEGRAM_ID: Staff(
                telegram_user_id=ACTOR_ADMIN_TELEGRAM_ID, clinic_id=CLINIC_ID, visibility_scope="clinic", is_doctor=False,
            ),
            OTHER_ADMIN_TELEGRAM_ID: Staff(
                telegram_user_id=OTHER_ADMIN_TELEGRAM_ID, clinic_id=CLINIC_ID, visibility_scope="clinic", is_doctor=False,
            ),
        }

    async def get_staff(self, telegram_user_id):
        return self.by_telegram_id.get(telegram_user_id)

    async def get_staff_by_clinic_id(self, clinic_id):
        return [s for s in self.by_telegram_id.values() if s.clinic_id == clinic_id]


class FakeClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=CLINIC_ID, name="Zub Mudrosti", token="t")


class FakeAppointmentRepository:
    def __init__(self, appointment, notifications=None, call_order=None):
        self.appointment = appointment
        self.notifications = list(notifications or [])
        self.notification_message_id_updates = []
        self.call_order = call_order if call_order is not None else []
        self.fail_delete = False
        self.deleted_ids = []
        self.recorded_notifications = []

    async def get_appointment_by_id(self, appointment_id):
        return self.appointment

    async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None):
        return []

    async def try_confirm_or_reject_pending(self, appointment_id, new_status, decided_by_user_id, status_updated_at):
        return True

    async def try_resolve_client_reschedule(
        self, appointment_id, accept, decided_by_user_id, status_updated_at, new_datetime=None,
    ):
        return True

    async def try_apply_new_datetime_immediately(
        self, appointment_id, new_datetime, decided_by_user_id, status_updated_at, expected_status,
    ):
        return True

    async def try_propose_new_datetime(
        self, appointment_id, new_datetime, decided_by_user_id, status_updated_at, expected_status,
    ):
        return True

    async def update_notification_message_id(self, appointment_id, message_id):
        self.notification_message_id_updates.append((appointment_id, message_id))

    async def get_appointment_notifications(self, appointment_id, kind):
        return [n for n in self.notifications if n.appointment_id == appointment_id and n.kind == kind]

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.appointment.status = status

    async def appointment_exists(self, appointment_id):
        return not self.fail_delete

    async def delete_appointment(self, appointment_id):
        self.call_order.append("delete")
        self.deleted_ids.append(appointment_id)

    async def add_appointment_notification(self, appointment_id, chat_id, message_id, kind):
        self.call_order.append("record")
        self.recorded_notifications.append((appointment_id, chat_id, message_id, kind))

    async def count_appointments_by_status(self, status, clinic_id, doctor_id=None, tab_bucket=False):
        return 0

    async def get_appointments_by_status_page(self, status, page, clinic_id, doctor_id, per_page, tab_bucket=False):
        return []

    async def update_admin_notification_message_id(self, appointment_id, message_id):
        pass

    async def create_appointment(self, appointment):
        appointment.id = self.appointment.id if self.appointment else 1
        self.appointment = appointment
        return appointment


class FakeNotificationService:
    def __init__(self, call_order=None):
        self.client_with_buttons_calls = []
        self.client_booking_rejected_calls = []
        self.client_reschedule_accepted_calls = []
        self.client_reschedule_rejected_calls = []
        self.staff_booking_confirmed_calls = []
        self.staff_booking_rejected_calls = []
        self.staff_reschedule_accepted_calls = []
        self.staff_reschedule_rejected_calls = []
        self.client_cancelled_by_admin_calls = []
        self.staff_appointment_cancelled_calls = []
        self.staff_appointment_created_calls = []
        self.invalidate_stale_decision_message = AsyncMock()
        self.call_order = call_order if call_order is not None else []

    async def notify_client_appointment_with_buttons(self, appointment, use_invite_kb=True, rescheduled=False):
        self.client_with_buttons_calls.append((appointment.id, use_invite_kb, rescheduled))
        return 111

    async def notify_client_booking_request_rejected(self, appointment):
        self.client_booking_rejected_calls.append(appointment.id)
        return True

    async def notify_client_reschedule_accepted(self, appointment):
        self.client_reschedule_accepted_calls.append(appointment.id)
        return True

    async def notify_client_reschedule_rejected(self, appointment):
        self.client_reschedule_rejected_calls.append(appointment.id)
        return True

    async def notify_staff_booking_confirmed(self, staff_telegram_id, appointment, actor_label, client_name):
        self.staff_booking_confirmed_calls.append((staff_telegram_id, appointment.id, actor_label, client_name))

    async def notify_staff_booking_rejected(self, staff_telegram_id, appointment, actor_label, client_name):
        self.staff_booking_rejected_calls.append((staff_telegram_id, appointment.id, actor_label, client_name))

    async def notify_staff_reschedule_decision_accepted(self, staff_telegram_id, appointment, actor_label, client_name):
        self.staff_reschedule_accepted_calls.append((staff_telegram_id, appointment.id, actor_label, client_name))

    async def notify_staff_reschedule_decision_rejected(self, staff_telegram_id, appointment, actor_label, client_name):
        self.staff_reschedule_rejected_calls.append((staff_telegram_id, appointment.id, actor_label, client_name))

    async def notify_client_appointment_cancelled_by_admin(self, appointment):
        self.call_order.append("notify_client")
        self.client_cancelled_by_admin_calls.append(appointment.id)
        return True

    async def notify_staff_appointment_cancelled(self, staff_telegram_id, appointment, actor_label, client_name, deleted=False):
        self.call_order.append("notify_staff")
        self.staff_appointment_cancelled_calls.append(
            (staff_telegram_id, appointment.id, actor_label, client_name, deleted)
        )
        return 222

    async def notify_staff_appointment_created(self, staff_telegram_id, appointment, actor_label, client_name):
        self.staff_appointment_created_calls.append(
            (staff_telegram_id, appointment.id, actor_label, client_name)
        )
        return 333


def _callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ACTOR_ADMIN_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.chat.id = 555
    callback_query.message.message_id = 777
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _state(**data):
    state = MagicMock()
    state.get_data = AsyncMock(return_value=data)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


# --- booking_requests.py: confirm_request / reject_request ---

@pytest.mark.asyncio
async def test_confirm_request_notifies_doctor_and_other_admin_but_not_actor():
    appointment = Appointment(
        clinic_id=CLINIC_ID, client_id=CLIENT_ID, doctor_id=DOCTOR_ID, datetime="2026-08-10 10:00",
        purpose="Konsultatsiya", created_by=CreatedBy.CLIENT, status=AppointmentStatus.PENDING, id=1,
    )
    appt_repo = FakeAppointmentRepository(appointment)
    notification_service = FakeNotificationService()
    router = create_admin_booking_requests_router(
        "zb", appt_repo, FakeUserRepo(_client(telegram_user_id=5000)), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service,
    )
    confirm_request = _find_handler(router, "confirm_request")
    callback_query = _callback_query()

    await confirm_request(callback_query, BookingRequestActionCB(action="confirm", appointment_id=1), _actor_admin())

    assert notification_service.staff_booking_confirmed_calls == [
        (DOCTOR_TELEGRAM_ID, 1, ACTOR_LABEL, CLIENT_NAME),
        (OTHER_ADMIN_TELEGRAM_ID, 1, ACTOR_LABEL, CLIENT_NAME),
    ]
    assert notification_service.staff_booking_rejected_calls == []
    actor_notified = any(call[0] == ACTOR_ADMIN_TELEGRAM_ID for call in notification_service.staff_booking_confirmed_calls)
    assert actor_notified is False


@pytest.mark.asyncio
async def test_reject_request_notifies_doctor_and_other_admin_but_not_actor():
    appointment = Appointment(
        clinic_id=CLINIC_ID, client_id=CLIENT_ID, doctor_id=DOCTOR_ID, datetime="2026-08-10 10:00",
        purpose="Konsultatsiya", created_by=CreatedBy.CLIENT, status=AppointmentStatus.PENDING, id=1,
    )
    appt_repo = FakeAppointmentRepository(appointment)
    notification_service = FakeNotificationService()
    router = create_admin_booking_requests_router(
        "zb", appt_repo, FakeUserRepo(_client(telegram_user_id=5000)), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service,
    )
    reject_request = _find_handler(router, "reject_request")
    callback_query = _callback_query()

    await reject_request(callback_query, BookingRequestActionCB(action="reject", appointment_id=1), _actor_admin())

    assert notification_service.staff_booking_rejected_calls == [
        (DOCTOR_TELEGRAM_ID, 1, ACTOR_LABEL, CLIENT_NAME),
        (OTHER_ADMIN_TELEGRAM_ID, 1, ACTOR_LABEL, CLIENT_NAME),
    ]
    assert notification_service.staff_booking_confirmed_calls == []
    actor_notified = any(call[0] == ACTOR_ADMIN_TELEGRAM_ID for call in notification_service.staff_booking_rejected_calls)
    assert actor_notified is False


@pytest.mark.asyncio
async def test_confirm_request_invalidates_sibling_notifications_with_appointment_summary():
    appointment = Appointment(
        clinic_id=CLINIC_ID, client_id=CLIENT_ID, doctor_id=DOCTOR_ID, datetime="2026-08-10 10:00",
        purpose="Konsultatsiya", created_by=CreatedBy.CLIENT, status=AppointmentStatus.PENDING, id=1,
    )
    sibling_notification = AppointmentNotification(appointment_id=1, chat_id=OTHER_ADMIN_TELEGRAM_ID, message_id=42, kind="booking")
    appt_repo = FakeAppointmentRepository(appointment, notifications=[sibling_notification])
    notification_service = FakeNotificationService()
    router = create_admin_booking_requests_router(
        "zb", appt_repo, FakeUserRepo(_client(telegram_user_id=5000)), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service,
    )
    confirm_request = _find_handler(router, "confirm_request")
    callback_query = _callback_query()

    await confirm_request(callback_query, BookingRequestActionCB(action="confirm", appointment_id=1), _actor_admin())

    expected_summary = build_appointment_card(appt_repo.appointment, _actor_admin().language)
    notification_service.invalidate_stale_decision_message.assert_awaited_once_with(
        OTHER_ADMIN_TELEGRAM_ID, 42, ACTOR_LABEL, {"ru": "подтверждена", "uz": "tasdiqlandi"},
        appointment_summary=expected_summary,
    )


# --- booking_requests.py: approve_propose_datetime (CONFIRMED branch) ---

@pytest.mark.asyncio
async def test_approve_propose_datetime_confirmed_branch_notifies_other_staff_in_booking_requests():
    appointment = Appointment(
        clinic_id=CLINIC_ID, client_id=CLIENT_ID, doctor_id=DOCTOR_ID, datetime="2026-08-10 10:00",
        purpose="Konsultatsiya", created_by=CreatedBy.CLIENT, status=AppointmentStatus.PENDING, id=1,
    )
    appt_repo = FakeAppointmentRepository(appointment)
    notification_service = FakeNotificationService()
    router = create_admin_booking_requests_router(
        "zb", appt_repo, FakeUserRepo(_client(telegram_user_id=None)), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service,
    )
    approve_propose_datetime = _find_handler(router, "approve_propose_datetime")
    callback_query = _callback_query()
    state = _state(
        appointment_datetime_parsed=datetime(2026, 8, 15, 12, 0),
        appointment_datetime_display="15.08.2026 12:00",
    )

    await approve_propose_datetime(
        callback_query, BookingRequestActionCB(action="approve_propose_datetime", appointment_id=1), state,
        _actor_admin(),
    )

    assert appointment.status == AppointmentStatus.CONFIRMED
    assert notification_service.staff_booking_confirmed_calls == [
        (DOCTOR_TELEGRAM_ID, 1, ACTOR_LABEL, CLIENT_NAME),
        (OTHER_ADMIN_TELEGRAM_ID, 1, ACTOR_LABEL, CLIENT_NAME),
    ]
    state.clear.assert_awaited_once()


# --- reschedule_requests.py: accept_reschedule / reject_reschedule ---

def _reschedule_appointment():
    return Appointment(
        clinic_id=CLINIC_ID, client_id=CLIENT_ID, doctor_id=DOCTOR_ID, datetime="2026-08-10 10:00",
        purpose="Konsultatsiya", created_by=CreatedBy.CLIENT, status=AppointmentStatus.CONFIRMED, id=2,
        proposed_datetime="2026-08-12 11:00", proposed_by=CreatedBy.CLIENT,
    )


@pytest.mark.asyncio
async def test_accept_reschedule_notifies_doctor_and_other_admin_but_not_actor():
    appointment = _reschedule_appointment()
    appt_repo = FakeAppointmentRepository(appointment)
    notification_service = FakeNotificationService()
    router = create_admin_reschedule_requests_router(
        "zb", appt_repo, FakeUserRepo(_client(telegram_user_id=5000)), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service,
    )
    accept_reschedule = _find_handler(router, "accept_reschedule")
    callback_query = _callback_query()

    await accept_reschedule(callback_query, RescheduleRequestActionCB(action="accept", appointment_id=2), _actor_admin())

    assert notification_service.staff_reschedule_accepted_calls == [
        (DOCTOR_TELEGRAM_ID, 2, ACTOR_LABEL, CLIENT_NAME),
        (OTHER_ADMIN_TELEGRAM_ID, 2, ACTOR_LABEL, CLIENT_NAME),
    ]
    assert notification_service.staff_reschedule_rejected_calls == []
    actor_notified = any(
        call[0] == ACTOR_ADMIN_TELEGRAM_ID for call in notification_service.staff_reschedule_accepted_calls
    )
    assert actor_notified is False


@pytest.mark.asyncio
async def test_reject_reschedule_notifies_doctor_and_other_admin_but_not_actor():
    appointment = _reschedule_appointment()
    appt_repo = FakeAppointmentRepository(appointment)
    notification_service = FakeNotificationService()
    router = create_admin_reschedule_requests_router(
        "zb", appt_repo, FakeUserRepo(_client(telegram_user_id=5000)), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service,
    )
    reject_reschedule = _find_handler(router, "reject_reschedule")
    callback_query = _callback_query()

    await reject_reschedule(callback_query, RescheduleRequestActionCB(action="reject", appointment_id=2), _actor_admin())

    assert notification_service.staff_reschedule_rejected_calls == [
        (DOCTOR_TELEGRAM_ID, 2, ACTOR_LABEL, CLIENT_NAME),
        (OTHER_ADMIN_TELEGRAM_ID, 2, ACTOR_LABEL, CLIENT_NAME),
    ]
    assert notification_service.staff_reschedule_accepted_calls == []
    actor_notified = any(
        call[0] == ACTOR_ADMIN_TELEGRAM_ID for call in notification_service.staff_reschedule_rejected_calls
    )
    assert actor_notified is False


# --- reschedule_requests.py: approve_propose_datetime (CONFIRMED branch) ---

@pytest.mark.asyncio
async def test_approve_propose_datetime_confirmed_branch_notifies_other_staff_in_reschedule_requests():
    appointment = _reschedule_appointment()
    appt_repo = FakeAppointmentRepository(appointment)
    notification_service = FakeNotificationService()
    router = create_admin_reschedule_requests_router(
        "zb", appt_repo, FakeUserRepo(_client(telegram_user_id=None)), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service,
    )
    approve_propose_datetime = _find_handler(router, "approve_propose_datetime")
    callback_query = _callback_query()
    state = _state(
        appointment_datetime_parsed=datetime(2026, 8, 20, 9, 0),
        appointment_datetime_display="20.08.2026 09:00",
    )

    await approve_propose_datetime(
        callback_query, RescheduleRequestActionCB(action="approve_propose_datetime", appointment_id=2), state,
        _actor_admin(),
    )

    assert appointment.status == AppointmentStatus.CONFIRMED
    assert notification_service.staff_reschedule_accepted_calls == [
        (DOCTOR_TELEGRAM_ID, 2, ACTOR_LABEL, CLIENT_NAME),
        (OTHER_ADMIN_TELEGRAM_ID, 2, ACTOR_LABEL, CLIENT_NAME),
    ]
    state.clear.assert_awaited_once()


# --- appointment_creation.py: finish() staff fan-out ---

@pytest.mark.asyncio
async def test_finish_notifies_doctor_and_other_admin_but_not_actor():
    client = _client(telegram_user_id=5000)
    appt_repo = FakeAppointmentRepository(appointment=None)
    notification_service = FakeNotificationService()
    router = create_admin_appointment_creation_router(
        "zb", appt_repo, FakeUserRepo(client), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service,
    )
    finish = _find_handler(router, "finish")
    callback_query = _callback_query()
    state = _state(
        phone=client.phone, appointment_datetime="2026-08-10 10:00", purpose="Konsultatsiya",
        staff_user_id=DOCTOR_ID,
    )

    await finish(callback_query, state, _actor_admin())

    staff_recipients = {call[0] for call in notification_service.staff_appointment_created_calls}
    assert staff_recipients == {DOCTOR_TELEGRAM_ID, OTHER_ADMIN_TELEGRAM_ID}
    assert all(call[2] == ACTOR_LABEL for call in notification_service.staff_appointment_created_calls)
    assert all(call[3] == CLIENT_NAME for call in notification_service.staff_appointment_created_calls)
    # The actor's own message (777) is also recorded by finish()'s own
    # record_notification call, separate from the staff fan-out.
    recorded_kinds = {(chat_id, kind) for _, chat_id, _, kind in appt_repo.recorded_notifications}
    assert recorded_kinds == {
        (ACTOR_ADMIN_TELEGRAM_ID, "creation"),
        (DOCTOR_TELEGRAM_ID, "creation"),
        (OTHER_ADMIN_TELEGRAM_ID, "creation"),
    }


# --- appointment_browser.py: set_status(CANCELLED) staff fan-out ---

def _browser_appointment(status=AppointmentStatus.CONFIRMED):
    return Appointment(
        clinic_id=CLINIC_ID, client_id=CLIENT_ID, doctor_id=DOCTOR_ID, datetime="2026-08-10 10:00",
        purpose="Konsultatsiya", created_by=CreatedBy.ADMIN, status=status, id=1,
    )


@pytest.mark.asyncio
async def test_set_status_cancelled_notifies_staff_with_cancelled_wording_and_records_notification():
    appt_repo = FakeAppointmentRepository(_browser_appointment())
    notification_service = FakeNotificationService()
    router = create_admin_appointment_browser_router(
        "zb", appt_repo, FakeUserRepo(_client(telegram_user_id=5000)), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service,
    )
    set_status = _find_handler(router, "set_status")
    callback_query = _callback_query()
    state = _state()

    await set_status(
        callback_query,
        ApptActionCB(action="set_status", appointment_id=1, mode="list", page=1, value="cancelled", post_appt=False),
        state, _actor_admin(),
    )

    assert appt_repo.appointment.status == AppointmentStatus.CANCELLED
    assert notification_service.client_cancelled_by_admin_calls == [1]

    staff_calls = notification_service.staff_appointment_cancelled_calls
    staff_recipients = {call[0] for call in staff_calls}
    assert staff_recipients == {DOCTOR_TELEGRAM_ID, OTHER_ADMIN_TELEGRAM_ID}
    assert all(call[4] is False for call in staff_calls)

    recorded_kinds = {(chat_id, kind) for _, chat_id, _, kind in appt_repo.recorded_notifications}
    assert recorded_kinds == {
        (DOCTOR_TELEGRAM_ID, "cancellation"),
        (OTHER_ADMIN_TELEGRAM_ID, "cancellation"),
    }


# --- appointment_browser.py: finish_delete() staff fan-out and delete-then-notify ordering ---

@pytest.mark.asyncio
async def test_finish_delete_notifies_staff_with_deleted_wording_after_delete_and_skips_recording():
    call_order = []
    appt_repo = FakeAppointmentRepository(_browser_appointment(), call_order=call_order)
    notification_service = FakeNotificationService(call_order=call_order)
    router = create_admin_appointment_browser_router(
        "zb", appt_repo, FakeUserRepo(_client(telegram_user_id=5000)), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service,
    )
    confirm_delete_notify = _find_handler(router, "confirm_delete_notify")
    callback_query = _callback_query()
    state = _state()

    await confirm_delete_notify(
        callback_query,
        ApptActionCB(action="confirm_delete_notify", appointment_id=1, mode="list", page=1),
        state, _actor_admin(),
    )

    assert appt_repo.deleted_ids == [1]
    assert notification_service.client_cancelled_by_admin_calls == [1]

    staff_calls = notification_service.staff_appointment_cancelled_calls
    staff_recipients = {call[0] for call in staff_calls}
    assert staff_recipients == {DOCTOR_TELEGRAM_ID, OTHER_ADMIN_TELEGRAM_ID}
    assert all(call[4] is True for call in staff_calls)

    # deleted=True must skip recording (the appointments row's FK is gone).
    assert appt_repo.recorded_notifications == []

    # delete must happen before any notification is sent.
    assert call_order[0] == "delete"
    assert set(call_order[1:]) == {"notify_client", "notify_staff"}


@pytest.mark.asyncio
async def test_finish_delete_sends_no_notifications_when_delete_fails():
    appt_repo = FakeAppointmentRepository(_browser_appointment())
    appt_repo.fail_delete = True
    notification_service = FakeNotificationService()
    router = create_admin_appointment_browser_router(
        "zb", appt_repo, FakeUserRepo(_client(telegram_user_id=5000)), FakeStaffRepo(), FakeClinicRepo(),
        notification_service=notification_service,
    )
    confirm_delete_notify = _find_handler(router, "confirm_delete_notify")
    callback_query = _callback_query()
    state = _state()

    await confirm_delete_notify(
        callback_query,
        ApptActionCB(action="confirm_delete_notify", appointment_id=1, mode="list", page=1),
        state, _actor_admin(),
    )

    callback_query.answer.assert_awaited_once()
    assert callback_query.answer.await_args.kwargs.get("show_alert") is True
    assert appt_repo.deleted_ids == []
    assert notification_service.client_cancelled_by_admin_calls == []
    assert notification_service.staff_appointment_cancelled_calls == []
