from bot.handlers.utils.admin_utils.appointment_browser_helpers import (
    build_appointment_button_text,
    format_appointment_button,
)
from bot.models.appointment import Appointment
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy


def _appointment(client_full_name: str | None, client_phone: str | None = "+998901234567") -> Appointment:
    return Appointment(
        clinic_id=1,
        client_id=7,
        datetime="2026-07-10 14:30",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        id=1,
        client_full_name=client_full_name,
        client_phone=client_phone,
    )


def test_build_appointment_button_text_includes_given_name_phone_and_datetime():
    text = build_appointment_button_text(_appointment("Иванов Иван"))

    assert text == "10.07 • 14:30 • Иван • 901234567"


def test_build_appointment_button_text_falls_back_when_client_name_missing():
    text = build_appointment_button_text(_appointment(None))

    assert text == "10.07 • 14:30 • Безымянный • 901234567"


def test_build_appointment_button_text_falls_back_when_client_name_empty_string():
    text = build_appointment_button_text(_appointment(""))

    assert text == "10.07 • 14:30 • Безымянный • 901234567"


def test_build_appointment_button_text_falls_back_when_phone_missing():
    text = build_appointment_button_text(_appointment("Иванов Иван", client_phone=None))

    assert text == "10.07 • 14:30 • Иван • —"


def test_build_appointment_button_text_falls_back_when_phone_empty_string():
    text = build_appointment_button_text(_appointment("Иванов Иван", client_phone=""))

    assert text == "10.07 • 14:30 • Иван • —"


def test_format_appointment_button_normal_case():
    text = format_appointment_button("Силкина Наталья", "+998901234567", "2026-07-16 14:30:00")

    assert text == "16.07 • 14:30 • Наталья • 901234567"


def test_format_appointment_button_falls_back_when_name_has_single_word():
    text = format_appointment_button("Наталья", "+998901234567", "2026-07-16 14:30:00")

    assert text == "16.07 • 14:30 • Наталья • 901234567"


def test_format_appointment_button_falls_back_when_phone_has_fewer_than_nine_digits():
    text = format_appointment_button("Силкина Наталья", "12345", "2026-07-16 14:30:00")

    assert text == "16.07 • 14:30 • Наталья • 12345"


def test_format_appointment_button_formats_datetime_without_seconds():
    text = format_appointment_button("Силкина Наталья", "+998901234567", "2026-07-16 14:30")

    assert text == "16.07 • 14:30 • Наталья • 901234567"


def test_format_appointment_button_falls_back_to_raw_value_when_datetime_unparseable():
    text = format_appointment_button("Силкина Наталья", "+998901234567", "not-a-real-datetime")

    assert text == "not-a-real-datetime • Наталья • 901234567"


def test_build_appointment_button_text_shows_marker_when_negotiating():
    appointment = _appointment("Иванов Иван")
    appointment.status = AppointmentStatus.CONFIRMED
    appointment.proposed_datetime = "2026-08-15 15:00"
    appointment.proposed_by = CreatedBy.CLIENT

    text = build_appointment_button_text(appointment)

    assert text.startswith("🔁 ")


def test_build_appointment_button_text_no_marker_when_confirmed_without_proposal():
    appointment = _appointment("Иванов Иван")
    appointment.status = AppointmentStatus.CONFIRMED

    text = build_appointment_button_text(appointment)

    assert "🔁" not in text


def test_build_appointment_button_text_no_marker_when_pending_with_proposal():
    appointment = _appointment("Иванов Иван")
    appointment.status = AppointmentStatus.PENDING
    appointment.proposed_datetime = "2026-08-15 15:00"
    appointment.proposed_by = CreatedBy.CLIENT

    text = build_appointment_button_text(appointment)

    assert "🔁" not in text
