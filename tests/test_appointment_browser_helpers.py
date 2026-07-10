from bot.handlers.utils.admin_utils.appointment_browser_helpers import (
    build_appointment_button_text,
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


def test_build_appointment_button_text_includes_client_name_phone_and_datetime():
    text = build_appointment_button_text(_appointment("Иванов Иван"))

    assert text == "📅 Иванов Иван · 90 123-45-67 · 2026-07-10 14:30"


def test_build_appointment_button_text_falls_back_when_client_name_missing():
    text = build_appointment_button_text(_appointment(None))

    assert text == "📅 Без имени · 90 123-45-67 · 2026-07-10 14:30"


def test_build_appointment_button_text_falls_back_when_client_name_empty_string():
    text = build_appointment_button_text(_appointment(""))

    assert text == "📅 Без имени · 90 123-45-67 · 2026-07-10 14:30"


def test_build_appointment_button_text_falls_back_when_phone_missing():
    text = build_appointment_button_text(_appointment("Иванов Иван", client_phone=None))

    assert text == "📅 Иванов Иван · — · 2026-07-10 14:30"


def test_build_appointment_button_text_falls_back_when_phone_empty_string():
    text = build_appointment_button_text(_appointment("Иванов Иван", client_phone=""))

    assert text == "📅 Иванов Иван · — · 2026-07-10 14:30"
