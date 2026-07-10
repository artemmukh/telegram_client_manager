from bot.handlers.admin.appointment_management.booking_requests import _format_datetime_value


def test_format_datetime_value_formats_valid_iso_datetime_for_display():
    result = _format_datetime_value("2026-08-15 15:00")

    assert result == "15 августа 2026, 15:00"


def test_format_datetime_value_falls_back_to_raw_string_on_invalid_input():
    result = _format_datetime_value("not-a-datetime")

    assert result == "not-a-datetime"
