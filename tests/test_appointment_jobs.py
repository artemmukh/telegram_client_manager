"""Coverage for the awaiting-party derivation used by pending-expiry staff logs.

`AppointmentManagement.awaiting_party` maps (status, status_actor) to the side
that owes the next answer. Staff proposals apply immediately and clear
`proposed_by`, so the turn flag is the last status actor, not the proposer.
"""
from bot.models.appointment import Appointment
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy, StatusActor


def _appt(status: AppointmentStatus, created_by: CreatedBy, status_actor: StatusActor | None):
    return Appointment(
        clinic_id=1,
        client_id=7,
        datetime="2026-09-20 09:00",
        purpose="Осмотр",
        created_by=created_by,
        status=status,
        status_actor=status_actor,
    )


def test_awaiting_party_client_booking_needs_clinic():
    appt = _appt(status=AppointmentStatus.PENDING, created_by=CreatedBy.CLIENT, status_actor=StatusActor.CLIENT)
    assert AppointmentManagement.awaiting_party(appt) == "clinic"


def test_awaiting_party_after_staff_proposal_is_client():
    # Staff applied new time immediately; proposed_by is NULL on purpose.
    appt = _appt(status=AppointmentStatus.PENDING, created_by=CreatedBy.CLIENT, status_actor=StatusActor.STAFF)
    assert AppointmentManagement.awaiting_party(appt) == "client"


def test_awaiting_party_admin_invite_needs_client():
    appt = _appt(status=AppointmentStatus.PENDING, created_by=CreatedBy.ADMIN, status_actor=StatusActor.STAFF)
    assert AppointmentManagement.awaiting_party(appt) == "client"


def test_awaiting_party_client_counter_offer_needs_clinic():
    appt = _appt(status=AppointmentStatus.PENDING, created_by=CreatedBy.ADMIN, status_actor=StatusActor.CLIENT)
    assert AppointmentManagement.awaiting_party(appt) == "clinic"


def test_awaiting_party_confirmed_is_none():
    appt = _appt(status=AppointmentStatus.CONFIRMED, created_by=CreatedBy.CLIENT, status_actor=StatusActor.STAFF)
    assert AppointmentManagement.awaiting_party(appt) is None


def test_awaiting_party_pending_without_actor_is_none():
    appt = _appt(status=AppointmentStatus.PENDING, created_by=CreatedBy.CLIENT, status_actor=None)
    assert AppointmentManagement.awaiting_party(appt) is None
