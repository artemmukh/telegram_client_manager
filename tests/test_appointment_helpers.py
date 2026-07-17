from bot.handlers.utils.admin_utils.appointment_helpers import build_appointment_card
from bot.models.appointment import Appointment
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy


def _appointment(**overrides) -> Appointment:
    fields = dict(
        clinic_id=1,
        client_id=7,
        datetime="2026-07-16 14:30:00",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        id=1,
    )
    fields.update(overrides)
    return Appointment(**fields)


def test_build_appointment_card_shows_formatted_time():
    card = build_appointment_card(_appointment())

    assert "Время: 16.07.2026 14:30" in card


def test_build_appointment_card_formats_time_without_seconds():
    card = build_appointment_card(_appointment(datetime="2026-07-16 14:30"))

    assert "Время: 16.07.2026 14:30" in card


def test_build_appointment_card_omits_doctor_lines_when_doctor_full_name_absent():
    card = build_appointment_card(_appointment())

    assert "Врач:" not in card
    assert "Телефон врача:" not in card


def test_build_appointment_card_shows_doctor_name_and_phone_when_present():
    card = build_appointment_card(
        _appointment(doctor_full_name="Петров Петр", doctor_phone="+998907654321", doctor_is_doctor=True)
    )

    assert "Врач: Петров Петр" in card
    assert "Телефон врача: +998907654321" in card


def test_build_appointment_card_shows_dash_for_doctor_phone_when_missing():
    card = build_appointment_card(_appointment(doctor_full_name="Петров Петр", doctor_is_doctor=True))

    assert "Врач: Петров Петр" in card
    assert "Телефон врача: —" in card


def test_build_appointment_card_omits_doctor_lines_when_not_flagged_as_doctor():
    card = build_appointment_card(
        _appointment(doctor_full_name="Петров Петр", doctor_phone="+998907654321", doctor_is_doctor=False)
    )

    assert "Врач:" not in card
    assert "Телефон врача:" not in card
