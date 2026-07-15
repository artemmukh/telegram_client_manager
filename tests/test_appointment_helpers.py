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
