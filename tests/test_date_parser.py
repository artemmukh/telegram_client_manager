from datetime import datetime

import pytz

from bot.models.appointment import Appointment
from bot.services.utils.date_parser import (
    format_appointment_card_datetime,
    get_current_tashkent_datetime,
    is_appointment_upcoming,
)
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy


def test_get_current_tashkent_datetime_returns_naive_datetime():
    result = get_current_tashkent_datetime()

    assert isinstance(result, datetime)
    assert result.tzinfo is None


def test_get_current_tashkent_datetime_is_close_to_real_now():
    result = get_current_tashkent_datetime()
    real_now = datetime.now(pytz.timezone("Asia/Tashkent")).replace(tzinfo=None)

    assert abs((result - real_now).total_seconds()) < 5


def test_format_appointment_card_datetime_formats_with_seconds():
    assert format_appointment_card_datetime("2026-07-16 14:30:00") == "16.07.2026 14:30"


def test_format_appointment_card_datetime_formats_without_seconds():
    assert format_appointment_card_datetime("2026-07-16 14:30") == "16.07.2026 14:30"


def test_format_appointment_card_datetime_falls_back_to_raw_value_when_unparseable():
    assert format_appointment_card_datetime("not-a-real-datetime") == "not-a-real-datetime"


def _appointment(**overrides):
    fields = dict(
        clinic_id=1,
        client_id=1,
        datetime="2026-07-10 14:30",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.CONFIRMED,
        id=1,
        clinic_name="Зуб Мудрости",
    )
    fields.update(overrides)
    return Appointment(**fields)


def test_is_appointment_upcoming_true_when_datetime_after_now():
    now = datetime(2026, 7, 10, 14, 0)
    appointment = _appointment(datetime="2026-07-10 14:30")

    assert is_appointment_upcoming(appointment, now) is True


def test_is_appointment_upcoming_false_when_datetime_before_now():
    now = datetime(2026, 7, 10, 15, 0)
    appointment = _appointment(datetime="2026-07-10 14:30")

    assert is_appointment_upcoming(appointment, now) is False


def test_is_appointment_upcoming_true_at_exact_boundary():
    now = datetime(2026, 7, 10, 14, 30)
    appointment = _appointment(datetime="2026-07-10 14:30")

    assert is_appointment_upcoming(appointment, now) is True


def test_is_appointment_upcoming_prefers_proposed_datetime_when_present():
    now = datetime(2026, 7, 10, 14, 45)
    appointment = _appointment(datetime="2026-07-10 14:30", proposed_datetime="2026-08-01 10:00")

    assert is_appointment_upcoming(appointment, now) is True


def test_is_appointment_upcoming_uses_proposed_datetime_even_if_it_is_past():
    now = datetime(2026, 7, 10, 14, 0)
    appointment = _appointment(datetime="2026-08-01 10:00", proposed_datetime="2026-07-01 10:00")

    assert is_appointment_upcoming(appointment, now) is False


def test_is_appointment_upcoming_false_on_unparseable_datetime():
    now = datetime(2026, 7, 10, 14, 0)
    appointment = _appointment(datetime="not-a-real-datetime")

    assert is_appointment_upcoming(appointment, now) is False
