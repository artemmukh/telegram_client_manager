import pytest

from bot.handlers.utils.client_utils.appointment_history_helpers import (
    build_history_button_text,
    build_history_card_text,
)
from bot.models.appointment import Appointment
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy, status_label


def _appointment(status: AppointmentStatus, purpose: str | None = "Консультация", clinic_name: str | None = "Клиника №1") -> Appointment:
    return Appointment(
        clinic_id=1,
        client_id=7,
        datetime="2026-07-15T14:30:00",
        purpose=purpose,
        created_by=CreatedBy.CLIENT,
        status=status,
        id=1,
        clinic_name=clinic_name,
    )


@pytest.mark.parametrize("status", list(AppointmentStatus))
def test_build_history_button_text_for_all_statuses(status):
    appointment = _appointment(status)

    text = build_history_button_text(appointment)

    expected_emoji = status_label(status).split()[0]
    assert text.startswith(expected_emoji)
    assert "2026" in text


@pytest.mark.parametrize("status", list(AppointmentStatus))
def test_build_history_card_text_for_all_statuses(status):
    appointment = _appointment(status)

    text = build_history_card_text(appointment)

    assert status_label(status) in text
    assert "Консультация" in text
    assert "Клиника №1" in text


def test_build_history_card_text_handles_missing_purpose():
    appointment = _appointment(AppointmentStatus.PENDING, purpose=None)

    text = build_history_card_text(appointment)

    assert "Услуга" not in text


def test_build_history_card_text_handles_missing_clinic_name():
    appointment = _appointment(AppointmentStatus.PENDING, clinic_name=None)

    text = build_history_card_text(appointment)

    assert "Информация не доступна" in text


def test_build_history_button_text_falls_back_to_raw_string_on_malformed_datetime():
    appointment = _appointment(AppointmentStatus.PENDING)
    appointment.datetime = "not-a-real-datetime"

    text = build_history_button_text(appointment)

    assert "not-a-real-datetime" in text


def test_build_history_card_text_falls_back_to_raw_string_on_malformed_datetime():
    appointment = _appointment(AppointmentStatus.PENDING)
    appointment.datetime = "not-a-real-datetime"

    text = build_history_card_text(appointment)

    assert "Дата и время: not-a-real-datetime" in text


class _FakeUnlabeledStatus:
    """Duck-types an AppointmentStatus member that has no entry in APPOINTMENT_STATUS_LABELS."""

    value = "archived"


def test_build_history_button_text_falls_back_to_status_value_for_unlabeled_status():
    appointment = _appointment(AppointmentStatus.PENDING)
    appointment.status = _FakeUnlabeledStatus()

    text = build_history_button_text(appointment)

    assert text.startswith("archived")


def test_build_history_card_text_falls_back_to_status_value_for_unlabeled_status():
    appointment = _appointment(AppointmentStatus.PENDING)
    appointment.status = _FakeUnlabeledStatus()

    text = build_history_card_text(appointment)

    assert "Статус: archived" in text


def test_build_history_card_text_shows_doctor_when_flagged_as_doctor():
    appointment = _appointment(AppointmentStatus.PENDING)
    appointment.doctor_full_name = "Петров Петр"
    appointment.doctor_phone = "+998907654321"
    appointment.doctor_is_doctor = True

    text = build_history_card_text(appointment)

    assert "Врач: Петров Петр" in text
    assert "Телефон врача: +998907654321" in text


def test_build_history_card_text_omits_doctor_when_not_flagged_as_doctor():
    appointment = _appointment(AppointmentStatus.PENDING)
    appointment.doctor_full_name = "Петров Петр"
    appointment.doctor_phone = "+998907654321"
    appointment.doctor_is_doctor = False

    text = build_history_card_text(appointment)

    assert "Врач:" not in text
    assert "Телефон врача:" not in text


def test_build_history_card_text_omits_doctor_when_name_absent():
    appointment = _appointment(AppointmentStatus.PENDING)

    text = build_history_card_text(appointment)

    assert "Врач:" not in text
    assert "Телефон врача:" not in text


def test_build_history_card_text_shows_own_proposal_when_proposed_by_client():
    appointment = _appointment(AppointmentStatus.CONFIRMED)
    appointment.proposed_datetime = "2026-08-15T15:00:00"
    appointment.proposed_by = CreatedBy.CLIENT

    text = build_history_card_text(appointment)

    assert "Вы предложили перенос на: 15 августа 2026, 15:00" in text


def test_build_history_card_text_shows_clinic_proposal_when_proposed_by_admin():
    appointment = _appointment(AppointmentStatus.CONFIRMED)
    appointment.proposed_datetime = "2026-08-15T15:00:00"
    appointment.proposed_by = CreatedBy.ADMIN

    text = build_history_card_text(appointment)

    assert "Клиника предложила перенос на: 15 августа 2026, 15:00" in text


def test_build_history_card_text_omits_proposal_line_when_no_proposal():
    appointment = _appointment(AppointmentStatus.CONFIRMED)

    text = build_history_card_text(appointment)

    assert "предложил" not in text


def test_build_history_button_text_shows_marker_when_negotiating():
    appointment = _appointment(AppointmentStatus.CONFIRMED)
    appointment.proposed_datetime = "2026-08-15T15:00:00"
    appointment.proposed_by = CreatedBy.ADMIN

    text = build_history_button_text(appointment)

    assert text.startswith("🔁")
    expected_emoji = status_label(AppointmentStatus.CONFIRMED).split()[0]
    assert expected_emoji in text


def test_build_history_button_text_no_marker_when_confirmed_without_proposal():
    appointment = _appointment(AppointmentStatus.CONFIRMED)

    text = build_history_button_text(appointment)

    assert "🔁" not in text


def test_build_history_button_text_no_marker_when_pending_with_proposal():
    """Marker is only for CONFIRMED + proposed_datetime negotiation; PENDING
    appointments with a proposed_datetime use their own PENDING wording."""
    appointment = _appointment(AppointmentStatus.PENDING)
    appointment.proposed_datetime = "2026-08-15T15:00:00"
    appointment.proposed_by = CreatedBy.ADMIN

    text = build_history_button_text(appointment)

    assert "🔁" not in text
