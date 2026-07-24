"""Handler-level regression tests for the AppointmentAlreadyDecidedError branch
added to each admin decision router (booking_requests.py, reschedule_requests.py,
appointment_completion.py).

Each test simulates a lost race: another staff member's decision already landed
on the appointment (decided_by_user_id recorded) by the time this admin's own
action reaches the atomic repository call, which is hard-wired here to always
return False (the guard failing itself is exercised at the repository level in
test_appointment_repository.py and at the service level in
test_appointment_management.py -- this file only proves the handler correctly
surfaces the alert and invalidates the actor's own stale message).

Follows the direct-callback-invocation pattern established in
test_booking_requests_ownership.py / test_reschedule_requests_ownership.py.
"""
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.admin.appointment_management.appointment_completion import (
    create_admin_completion_router,
)
from bot.handlers.admin.appointment_management.booking_requests import (
    create_admin_booking_requests_router,
)
from bot.handlers.admin.appointment_management.reschedule_requests import (
    create_admin_reschedule_requests_router,
)
from bot.keyboards.admin.record_management_kb.booking_request_cb import BookingRequestActionCB
from bot.keyboards.admin.record_management_kb.completion_followup_cb import CompletionFollowupCB
from bot.keyboards.admin.record_management_kb.reschedule_request_cb import RescheduleRequestActionCB
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


ADMIN_TELEGRAM_ID = 999
ADMIN_ID = 1
WINNER_ID = 55
WINNER_TELEGRAM_ID = 2000
DECIDED_LABEL = "Администратор Ivanova Irina"


class FakeUserRepo:
    def __init__(self):
        self.by_telegram_id = {
            ADMIN_TELEGRAM_ID: User(
                full_name="Petrov Petr", phone="+998907654321", role=Role.ADMIN,
                telegram_user_id=ADMIN_TELEGRAM_ID, ID=ADMIN_ID, clinic_id=1, clinic_name="Zub Mudrosti",
            ),
        }
        self.by_id = {
            WINNER_ID: User(
                full_name="Ivanova Irina", phone="+998901112233", role=Role.ADMIN,
                telegram_user_id=WINNER_TELEGRAM_ID, ID=WINNER_ID, clinic_id=1, clinic_name="Zub Mudrosti",
            ),
        }

    async def get_user_by_telegram_id(self, telegram_user_id):
        return self.by_telegram_id.get(telegram_user_id)

    async def get_user_by_id(self, user_id):
        return self.by_id.get(user_id)


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=1, visibility_scope="clinic")


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
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _notification_service():
    service = MagicMock()
    service.invalidate_stale_decision_message = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_confirm_request_shows_alert_and_invalidates_own_message_on_lost_race():
    class FakeAppointmentRepository:
        def __init__(self, appointment):
            self.appointment = appointment

        async def get_appointment_by_id(self, appointment_id):
            return self.appointment

        async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None):
            return []

        async def try_confirm_or_reject_pending(self, appointment_id, new_status, decided_by_user_id, status_updated_at):
            return False

    appointment = Appointment(
        clinic_id=1, client_id=7, doctor_id=5, datetime="2026-08-01 10:00", purpose="Konsultatsiya",
        created_by=CreatedBy.CLIENT, status=AppointmentStatus.CONFIRMED, id=1, decided_by_user_id=WINNER_ID,
    )
    appt_repo = FakeAppointmentRepository(appointment)
    notification_service = _notification_service()
    router = create_admin_booking_requests_router(
        appt_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(), notification_service=notification_service,
    )
    confirm_request = _find_handler(router, "confirm_request")
    callback_query = _callback_query()

    await confirm_request(callback_query, BookingRequestActionCB(action="confirm", appointment_id=1))

    callback_query.answer.assert_called_once()
    args, kwargs = callback_query.answer.call_args
    assert "уже обработана" in args[0]
    assert "Ivanova Irina" in args[0]
    assert kwargs == {"show_alert": True}
    notification_service.invalidate_stale_decision_message.assert_awaited_once_with(
        555, 777, DECIDED_LABEL, "подтверждена"
    )


@pytest.mark.asyncio
async def test_accept_reschedule_shows_alert_and_invalidates_own_message_on_lost_race():
    class FakeAppointmentRepository:
        """CAS-flip fake: accept_client_reschedule requires proposed_by==CLIENT
        with a non-null proposed_datetime to even reach the CAS call, but the
        colleague who actually won the race leaves the row CONFIRMED with the
        proposal cleared -- a single shared object can't represent both states,
        so try_resolve_client_reschedule flips self.current to the winner's
        final row at the moment the CAS is (hypothetically) attempted, mirroring
        the real TOCTOU race against the DB."""

        def __init__(self, pre_race, post_race):
            self.current = pre_race
            self.post_race = post_race

        async def get_appointment_by_id(self, appointment_id):
            return self.current

        async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None):
            return []

        async def try_resolve_client_reschedule(
            self, appointment_id, accept, decided_by_user_id, status_updated_at, new_datetime=None
        ):
            self.current = self.post_race
            return False

    pre_race = Appointment(
        clinic_id=1, client_id=7, doctor_id=5, datetime="2026-08-01 10:00", purpose="Konsultatsiya",
        created_by=CreatedBy.CLIENT, status=AppointmentStatus.CONFIRMED, id=1,
        proposed_datetime="2026-08-05 09:00", proposed_by=CreatedBy.CLIENT,
    )
    post_race = Appointment(
        clinic_id=1, client_id=7, doctor_id=5, datetime="2026-08-05 09:00", purpose="Konsultatsiya",
        created_by=CreatedBy.CLIENT, status=AppointmentStatus.CONFIRMED, id=1,
        proposed_datetime=None, proposed_by=None, decided_by_user_id=WINNER_ID,
    )
    appt_repo = FakeAppointmentRepository(pre_race, post_race)
    notification_service = _notification_service()
    router = create_admin_reschedule_requests_router(
        appt_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(), notification_service=notification_service,
    )
    accept_reschedule = _find_handler(router, "accept_reschedule")
    callback_query = _callback_query()

    await accept_reschedule(callback_query, RescheduleRequestActionCB(action="accept", appointment_id=1))

    callback_query.answer.assert_called_once()
    args, kwargs = callback_query.answer.call_args
    assert "уже обработана" in args[0]
    assert "Ivanova Irina" in args[0]
    assert kwargs == {"show_alert": True}
    notification_service.invalidate_stale_decision_message.assert_awaited_once_with(
        555, 777, DECIDED_LABEL, "перенос принят"
    )


@pytest.mark.asyncio
async def test_skip_edit_shows_alert_and_invalidates_own_message_on_lost_race():
    class FakeAppointmentRepository:
        def __init__(self, appointment):
            self.appointment = appointment

        async def get_appointment_by_id(self, appointment_id):
            return self.appointment

        async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None):
            return []

        async def try_complete_appointment(self, appointment_id, decided_by_user_id, status_updated_at):
            return False

    appointment = Appointment(
        clinic_id=1, client_id=1, doctor_id=ADMIN_ID, datetime="2026-07-10 10:00", purpose="Konsultatsiya",
        created_by=CreatedBy.ADMIN, status=AppointmentStatus.COMPLETED, id=1, decided_by_user_id=WINNER_ID,
    )
    appt_repo = FakeAppointmentRepository(appointment)
    notification_service = _notification_service()
    router = create_admin_completion_router(
        appt_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(), notification_service=notification_service,
    )
    skip_edit = _find_handler(router, "skip_edit")
    callback_query = _callback_query()

    await skip_edit(callback_query, CompletionFollowupCB(action="skip", appointment_id=1))

    callback_query.answer.assert_called_once_with(
        "Запись уже автозавершена, вы можете скорректировать её в «Завершённые»", show_alert=True,
    )
    notification_service.invalidate_stale_decision_message.assert_awaited_once_with(
        555, 777, DECIDED_LABEL, "приём завершён"
    )


@pytest.mark.asyncio
async def test_approve_propose_datetime_shows_alert_and_invalidates_own_message_on_lost_race():
    """Handler sitting directly on top of the try_propose_new_datetime CAS fix:
    another admin already proposed a different time on the same PENDING booking
    request by the time this admin's own propose reaches the atomic repository
    call. propose_new_datetime requires the row to still show no ADMIN-side
    proposal to even attempt the CAS, but the winner's committed row has one --
    a single shared object can't represent both states, so try_propose_new_datetime
    flips self.current to the winner's final row at the moment the CAS is
    (hypothetically) attempted, mirroring the real TOCTOU race against the DB."""

    class FakeAppointmentRepository:
        def __init__(self, pre_race, post_race):
            self.current = pre_race
            self.post_race = post_race

        async def get_appointment_by_id(self, appointment_id):
            return self.current

        async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None):
            return []

        async def try_propose_new_datetime(
            self, appointment_id, proposed_datetime, proposed_by, decided_by_user_id, expected_status
        ):
            self.current = self.post_race
            return False

    pre_race = Appointment(
        clinic_id=1, client_id=7, doctor_id=5, datetime="2026-08-01 10:00", purpose="Konsultatsiya",
        created_by=CreatedBy.CLIENT, status=AppointmentStatus.PENDING, id=1,
    )
    post_race = Appointment(
        clinic_id=1, client_id=7, doctor_id=5, datetime="2026-08-01 10:00", purpose="Konsultatsiya",
        created_by=CreatedBy.CLIENT, status=AppointmentStatus.PENDING, id=1,
        proposed_datetime="2026-08-06 11:00", proposed_by=CreatedBy.ADMIN, decided_by_user_id=WINNER_ID,
    )
    appt_repo = FakeAppointmentRepository(pre_race, post_race)
    notification_service = _notification_service()
    router = create_admin_booking_requests_router(
        appt_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(), notification_service=notification_service,
    )
    approve_propose_datetime = _find_handler(router, "approve_propose_datetime")
    callback_query = _callback_query()
    state = MagicMock()
    state.get_data = AsyncMock(return_value={
        "appointment_datetime_parsed": datetime(2026, 8, 5, 12, 0),
        "appointment_datetime_display": "05.08.2026 12:00",
    })
    state.clear = AsyncMock()

    await approve_propose_datetime(
        callback_query, BookingRequestActionCB(action="approve_propose_datetime", appointment_id=1), state,
    )

    callback_query.answer.assert_called_once()
    args, kwargs = callback_query.answer.call_args
    assert "уже обработана" in args[0]
    assert "Ivanova Irina" in args[0]
    assert kwargs == {"show_alert": True}
    notification_service.invalidate_stale_decision_message.assert_awaited_once_with(
        555, 777, DECIDED_LABEL, "предложено другое время"
    )
    state.clear.assert_awaited_once()
