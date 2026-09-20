"""Guard rails for the pending-expiry prelude helper.

`_pending_expiry_context` must be called BEFORE the appointment is mutated
(expire_pending_request resets status_actor to SYSTEM, which would silently
change the derived awaiting party). The guard rejects any non-PENDING record.
"""
import pytest

from bot.models.appointment import Appointment
from bot.services.appointment.appointment_jobs import (
    _pending_expiry_context,
    resolve_pending_expiry,
)
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy, StatusActor


def _appointment(status: AppointmentStatus) -> Appointment:
    return Appointment(
        clinic_id=1, client_id=7, datetime="2027-08-20 09:00",
        purpose="Konsultatsiya", created_by=CreatedBy.CLIENT, status=status,
        id=2, status_actor=StatusActor.CLIENT,
    )


def test_pending_expiry_context_accepts_pending_appointment():
    party, deadline = _pending_expiry_context(_appointment(AppointmentStatus.PENDING))

    assert party == "clinic"
    assert deadline.isoformat() == "2027-08-20T07:00:00"


@pytest.mark.parametrize(
    "status",
    [AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED],
)
def test_pending_expiry_context_rejects_mutated_appointment(status):
    with pytest.raises(ValueError, match="PENDING"):
        _pending_expiry_context(_appointment(status))


class _FakeAppointmentManagement:
    def __init__(self, appointment):
        self.appointment = appointment

    async def get_appointment_by_id(self, appointment_id):
        return self.appointment


@pytest.mark.asyncio
async def test_resolve_pending_expiry_returns_none_when_appointment_missing():
    assert await resolve_pending_expiry(_FakeAppointmentManagement(None), 2) is None


@pytest.mark.asyncio
async def test_resolve_pending_expiry_returns_context_for_pending_appointment():
    context = await resolve_pending_expiry(
        _FakeAppointmentManagement(_appointment(AppointmentStatus.PENDING)), 2,
    )

    assert context is not None
    party, deadline = context
    assert party == "clinic"
    assert deadline.isoformat() == "2027-08-20T07:00:00"


@pytest.mark.asyncio
async def test_resolve_pending_expiry_returns_none_when_already_mutated():
    # A racing confirm/reject won before the job fired: the guard turns the
    # post-mutation record into a plain no-op instead of a wrong-party log.
    assert await resolve_pending_expiry(
        _FakeAppointmentManagement(_appointment(AppointmentStatus.CONFIRMED)), 2,
    ) is None
