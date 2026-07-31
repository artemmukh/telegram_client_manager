"""Handler-level test for appointment_browser.py's approve_new_datetime.

PR2 Part 2: admin editing the datetime of a CONFIRMED appointment through the
browser card no longer force-overwrites it (update_datetime); it now proposes
a new time via AppointmentManagement.propose_new_datetime and resyncs the full
job set through AppointmentScheduler.resync_appointment_jobs, instead of the
old one-sided update_datetime + manual cancel/schedule reminder/completion/
auto_confirm sequence (which is no longer used for new appointments).

Thin, direct-call test in the same style as test_appointment_reschedule_handler.py:
build the router with fake repos, pull the decorated `approve_new_datetime`
callback out of router.callback_query.handlers, and invoke it directly with
mock aiogram objects.
"""
import pytest
from dataclasses import replace
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.admin.appointment_management.appointment_browser import (
    create_admin_appointment_browser_router,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import ApptActionCB
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


ADMIN_TELEGRAM_ID = 999


class FakeAppointmentRepository:
    def __init__(self, appointment, copy_on_read=False):
        self.appointment = appointment
        self.copy_on_read = copy_on_read
        self.proposed_datetime_updates = []
        self.proposed_by_updates = []
        self.proposal_message_id_updates = []

    async def get_appointment_by_id(self, appointment_id):
        # copy_on_read=True mirrors the real repository, which maps a fresh
        # Appointment instance from the DB row on every SELECT -- needed so a
        # test can prove the handler captured a value *before* a later
        # in-place mutation, rather than incidentally reading the same
        # shared, already-mutated object (see the "old time" regression test
        # below). Other tests in this file rely on the previous
        # shared-identity behavior, so it stays opt-in.
        return replace(self.appointment) if self.copy_on_read else self.appointment

    async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses=None):
        return []

    async def update_proposed_datetime(self, appointment_id, proposed_datetime):
        self.proposed_datetime_updates.append((appointment_id, proposed_datetime))
        self.appointment.proposed_datetime = proposed_datetime

    async def update_proposed_by(self, appointment_id, proposed_by):
        self.proposed_by_updates.append((appointment_id, proposed_by))
        self.appointment.proposed_by = proposed_by

    async def update_proposal_message_id(self, appointment_id, message_id):
        self.proposal_message_id_updates.append((appointment_id, message_id))

    async def try_propose_new_datetime(
        self, appointment_id, proposed_datetime, proposed_by, decided_by_user_id, expected_status
    ):
        # Deliberately does not mutate self.appointment -- AppointmentManagement.
        # propose_new_datetime() applies the equivalent field updates itself
        # afterward, mirroring the real repository which only touches the DB
        # row, never the caller's Python object.
        if self.appointment.status.value != expected_status:
            return False
        if self.appointment.proposed_datetime is not None and self.appointment.proposed_by == CreatedBy.ADMIN:
            return False

        self.proposed_datetime_updates.append((appointment_id, proposed_datetime))
        self.proposed_by_updates.append((appointment_id, CreatedBy(proposed_by)))
        return True

    async def try_apply_new_datetime_immediately(
        self, appointment_id, new_datetime, decided_by_user_id, status_updated_at, expected_status
    ):
        if self.appointment.status.value != expected_status:
            return False
        if self.appointment.proposed_datetime is not None and self.appointment.proposed_by == CreatedBy.ADMIN:
            return False

        self.proposed_datetime_updates.append((appointment_id, None))
        self.proposed_by_updates.append((appointment_id, None))
        return True


class FakeUserRepo:
    def __init__(self, client=None):
        self.client = client

    async def get_user_by_telegram_id(self, telegram_user_id):
        return User(
            full_name="Петров Петр",
            phone="+998907654321",
            role=Role.ADMIN,
            telegram_user_id=ADMIN_TELEGRAM_ID,
            ID=1,
            clinic_id=1,
            clinic_name="Зуб Мудрости",
        )

    async def get_client_by_id(self, user_id):
        return self.client


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=1, visibility_scope="clinic")


class FakeClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=1, name="Зуб Мудрости", token="t")


def _confirmed_appointment():
    return Appointment(
        clinic_id=1,
        client_id=7,
        datetime="2026-08-01 10:00",
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=AppointmentStatus.CONFIRMED,
        id=1,
    )


def _get_approve_new_datetime_handler(router):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == "approve_new_datetime":
            return handler.callback
    raise AssertionError("approve_new_datetime handler not found on router")


def _make_callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
    callback_query.message.edit_text = AsyncMock()
    callback_query.answer = AsyncMock()
    return callback_query


def _make_state():
    state = MagicMock()
    state.get_data = AsyncMock(return_value={
        "appointment_datetime_parsed": datetime(2026, 8, 5, 12, 0),
        "appointment_datetime_display": "05.08.2026 12:00",
    })
    state.clear = AsyncMock()
    return state


@pytest.mark.asyncio
async def test_approve_new_datetime_proposes_instead_of_forcing_and_resyncs_jobs():
    appointment = _confirmed_appointment()
    appt_repo = FakeAppointmentRepository(appointment)

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()
    appointment_scheduler.schedule_appointment_reminders = AsyncMock()
    appointment_scheduler.schedule_appointment_completion = AsyncMock()
    appointment_scheduler.schedule_auto_confirm = AsyncMock()

    notification_service = MagicMock()
    notification_service.notify_client_appointment_reschedule_proposed = AsyncMock(return_value=321)

    router = create_admin_appointment_browser_router(
        appt_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(),
        appointment_scheduler=appointment_scheduler, notification_service=notification_service,
    )
    approve_new_datetime = _get_approve_new_datetime_handler(router)
    callback_query = _make_callback_query()

    await approve_new_datetime(
        callback_query, ApptActionCB(action="approve_new_datetime", appointment_id=1, mode="all", page=1),
        _make_state(),
    )

    # propose_new_datetime was used, not a forced update_datetime: the appointment
    # stays CONFIRMED with the new time recorded only as a proposal.
    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appointment.datetime == "2026-08-01 10:00"
    assert appt_repo.proposed_datetime_updates == [(1, "2026-08-05 12:00")]
    assert appt_repo.proposed_by_updates == [(1, CreatedBy.ADMIN)]

    # Full job set is recomputed via resync_appointment_jobs, not the old manual
    # cancel/schedule reminder+completion+auto_confirm sequence.
    appointment_scheduler.resync_appointment_jobs.assert_awaited_once_with(appointment)
    appointment_scheduler.schedule_appointment_reminders.assert_not_awaited()
    appointment_scheduler.schedule_appointment_completion.assert_not_awaited()
    appointment_scheduler.schedule_auto_confirm.assert_not_awaited()

    notification_service.notify_client_appointment_reschedule_proposed.assert_awaited_once_with(appointment)
    assert appt_repo.proposal_message_id_updates == [(1, 321)]

    # Toast shows both the pre-proposal (original confirmed) time and the newly
    # proposed time, not just the new time.
    toast_text = callback_query.message.edit_text.call_args.args[0]
    assert "1 августа 2026, 10:00" in toast_text
    assert "05.08.2026 12:00" in toast_text


@pytest.mark.asyncio
async def test_approve_new_datetime_immediately_applies_when_client_has_no_telegram_account():
    """A client with no linked Telegram account can never confirm a proposal,
    so the service applies the new time immediately (status stays CONFIRMED,
    datetime updated in place). The handler must then skip the
    notify_client_appointment_reschedule_proposed call and the "waiting on
    client" message, and the "old time" shown must be the true pre-call
    appointment.datetime, not the (now-mutated) post-call value."""
    appointment = _confirmed_appointment()
    # copy_on_read=True: mirrors the real repository (fresh Appointment mapped
    # from the row on every SELECT), so the handler's pre-call owned_appointment
    # fetch and the service's own internal fetch/mutation are genuinely
    # distinct objects -- required to catch the old_display regression below.
    appt_repo = FakeAppointmentRepository(appointment, copy_on_read=True)
    client = User(
        full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, ID=7, telegram_user_id=None,
    )

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()

    notification_service = MagicMock()
    notification_service.notify_client_appointment_reschedule_proposed = AsyncMock(return_value=321)

    router = create_admin_appointment_browser_router(
        appt_repo, FakeUserRepo(client), FakeStaffRepo(), FakeClinicRepo(),
        appointment_scheduler=appointment_scheduler, notification_service=notification_service,
    )
    approve_new_datetime = _get_approve_new_datetime_handler(router)
    callback_query = _make_callback_query()
    state = _make_state()

    await approve_new_datetime(
        callback_query, ApptActionCB(action="approve_new_datetime", appointment_id=1, mode="all", page=1),
        state,
    )

    resynced = appointment_scheduler.resync_appointment_jobs.await_args.args[0]
    assert resynced.status is AppointmentStatus.CONFIRMED
    assert resynced.datetime == "2026-08-05 12:00"
    assert resynced.proposed_datetime is None
    assert resynced.proposed_by is None
    assert appt_repo.proposed_datetime_updates == [(1, None)]
    assert appt_repo.proposed_by_updates == [(1, None)]

    appointment_scheduler.resync_appointment_jobs.assert_awaited_once()
    notification_service.notify_client_appointment_reschedule_proposed.assert_not_awaited()
    assert appt_repo.proposal_message_id_updates == []

    toast_text = callback_query.message.edit_text.call_args.args[0]
    assert "Ожидаем ответа клиента" not in toast_text
    # Regression check: the displayed "old time" must be the true original
    # (pre-call) datetime, not appointment.datetime after the service mutated
    # it to the new value.
    assert "1 августа 2026, 10:00" in toast_text
    assert "05.08.2026 12:00" in toast_text
    callback_query.answer.assert_awaited_once_with("Время записи изменено")
    state.clear.assert_awaited_once()
