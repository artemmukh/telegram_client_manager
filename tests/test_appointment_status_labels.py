import pytest

from bot.models.appointment import Appointment
from bot.utils.appointment_enums import (
    AppointmentStatus,
    CreatedBy,
    StatusActor,
    appointment_status_label,
)


def _appointment(
    status: AppointmentStatus,
    *,
    created_by: CreatedBy = CreatedBy.CLIENT,
    proposed_by: CreatedBy | None = None,
    status_actor: StatusActor | None = None,
) -> Appointment:
    return Appointment(
        clinic_id=1,
        client_id=1,
        datetime="2026-09-15 10:00",
        purpose="Консультация",
        created_by=created_by,
        status=status,
        proposed_by=proposed_by,
        status_actor=status_actor,
    )


@pytest.mark.parametrize(
    ("appointment", "expected"),
    [
        (_appointment(AppointmentStatus.PENDING), "ожидает подтверждения врача"),
        (
            _appointment(AppointmentStatus.PENDING, created_by=CreatedBy.ADMIN),
            "ожидает подтверждения клиента",
        ),
        (
            _appointment(AppointmentStatus.PENDING, proposed_by=CreatedBy.CLIENT),
            "ожидает подтверждения врача",
        ),
        (
            _appointment(AppointmentStatus.PENDING, proposed_by=CreatedBy.ADMIN),
            "ожидает подтверждения клиента",
        ),
        (_appointment(AppointmentStatus.CONFIRMED), "подтверждено врачом"),
        (
            _appointment(AppointmentStatus.CONFIRMED, created_by=CreatedBy.ADMIN),
            "подтверждено клиентом",
        ),
        (_appointment(AppointmentStatus.CANCELLED), "отменена врачом"),
        (
            _appointment(AppointmentStatus.CANCELLED, created_by=CreatedBy.ADMIN),
            "отменена клиентом",
        ),
    ],
)
def test_appointment_status_label_includes_decision_party(appointment, expected):
    assert expected in appointment_status_label(appointment)


def test_non_decision_statuses_keep_existing_labels():
    appointment = _appointment(AppointmentStatus.COMPLETED, created_by=CreatedBy.ADMIN)

    assert appointment_status_label(appointment) == "✔️ завершена"


def test_persisted_status_actor_overrides_creator_fallback():
    client_cancelled = _appointment(
        AppointmentStatus.CANCELLED,
        created_by=CreatedBy.CLIENT,
        status_actor=StatusActor.CLIENT,
    )
    staff_confirmed = _appointment(
        AppointmentStatus.CONFIRMED,
        created_by=CreatedBy.ADMIN,
        status_actor=StatusActor.STAFF,
    )

    assert "отменена клиентом" in appointment_status_label(client_cancelled)
    assert "подтверждено врачом" in appointment_status_label(staff_confirmed)


def test_staff_reschedule_to_pending_waits_for_client():
    appointment = _appointment(
        AppointmentStatus.PENDING,
        created_by=CreatedBy.CLIENT,
        status_actor=StatusActor.STAFF,
    )

    assert "ожидает подтверждения клиента" in appointment_status_label(appointment)


def test_appointment_status_label_supports_uzbek():
    appointment = _appointment(AppointmentStatus.PENDING, created_by=CreatedBy.ADMIN)

    assert appointment_status_label(appointment, "uz") == "🕐 mijoz tasdig'ini kutmoqda"
