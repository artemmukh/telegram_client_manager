from datetime import datetime

import pytz

import bot.services.utils.date_parser as date_parser_module
from bot.models.appointment import Appointment
from bot.services.utils.date_parser import (
    MAX_YEARS_AHEAD,
    RESCHEDULE_NEGOTIATION_NOTE,
    build_reschedule_proposal_line,
    format_appointment_card_datetime,
    format_datetime_for_confirmation,
    format_datetime_for_display,
    get_current_tashkent_datetime,
    is_appointment_upcoming,
    parse_ru_datetime,
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


def test_parse_ru_datetime_parses_normal_short_input():
    assert parse_ru_datetime("24.07.2026 12:30") is not None


def test_parse_ru_datetime_rejects_text_over_fifty_chars_without_calling_dateparser(monkeypatch):
    import bot.services.utils.date_parser as date_parser_module

    called = False

    def _fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(date_parser_module.dateparser, "parse", _fail_if_called)

    text = "24.07.2026 12:30" + "x" * 35
    assert len(text) == 51

    assert parse_ru_datetime(text) is None
    assert called is False


def test_parse_ru_datetime_rejects_ambiguous_two_digit_year_misread():
    """Regression test: dateparser used to misread the trailing '16' in
    '30.07 16' as a 2-digit year (defaulting the time to 00:00), producing
    2116-07-30 00:00:00 instead of failing. The MAX_YEARS_AHEAD guard now
    rejects any parse result that lands too far in the future."""
    assert parse_ru_datetime("30.07 16") is None


def test_parse_ru_datetime_still_parses_explicit_time_with_colon():
    now = get_current_tashkent_datetime()
    expected_year = now.year if (now.month, now.day) <= (7, 30) else now.year + 1

    result = parse_ru_datetime("30.07 16:00")

    assert result is not None
    assert (result.year, result.month, result.day, result.hour, result.minute) == (
        expected_year, 7, 30, 16, 0,
    )


def test_parse_ru_datetime_still_parses_explicit_time_with_dot_separator():
    now = get_current_tashkent_datetime()
    expected_year = now.year if (now.month, now.day) <= (7, 30) else now.year + 1

    result = parse_ru_datetime("30.07 16.00")

    assert result is not None
    assert (result.year, result.month, result.day, result.hour, result.minute) == (
        expected_year, 7, 30, 16, 0,
    )


def test_parse_ru_datetime_uses_relative_base_deterministically(monkeypatch):
    fixed_now = datetime(2026, 7, 29, 9, 0)
    monkeypatch.setattr(date_parser_module, "get_current_tashkent_datetime", lambda: fixed_now)

    result = parse_ru_datetime("завтра в 3 часа")

    assert result is not None
    assert (result.year, result.month, result.day, result.hour, result.minute) == (
        2026, 7, 30, 15, 0,
    )


def test_parse_ru_datetime_relative_base_passed_to_dateparser(monkeypatch):
    fixed_now = datetime(2026, 7, 29, 9, 0)
    monkeypatch.setattr(date_parser_module, "get_current_tashkent_datetime", lambda: fixed_now)

    captured_settings = {}

    def _fake_parse(text, languages=None, date_formats=None, settings=None):
        captured_settings.update(settings or {})
        return None

    monkeypatch.setattr(date_parser_module.dateparser, "parse", _fake_parse)

    parse_ru_datetime("завтра в 3 часа")

    assert captured_settings["RELATIVE_BASE"] == fixed_now


def test_parse_ru_datetime_accepts_year_exactly_at_max_years_ahead_boundary(monkeypatch):
    fixed_now = datetime(2026, 7, 29, 9, 0)
    monkeypatch.setattr(date_parser_module, "get_current_tashkent_datetime", lambda: fixed_now)

    boundary_dt = datetime(fixed_now.year + MAX_YEARS_AHEAD, 7, 30, 16, 0)
    monkeypatch.setattr(date_parser_module.dateparser, "parse", lambda *a, **k: boundary_dt)

    result = parse_ru_datetime("30.07 16:00")

    assert result == boundary_dt


def test_parse_ru_datetime_rejects_year_past_max_years_ahead_boundary(monkeypatch):
    fixed_now = datetime(2026, 7, 29, 9, 0)
    monkeypatch.setattr(date_parser_module, "get_current_tashkent_datetime", lambda: fixed_now)

    over_boundary_dt = datetime(fixed_now.year + MAX_YEARS_AHEAD + 1, 7, 30, 16, 0)
    monkeypatch.setattr(date_parser_module.dateparser, "parse", lambda *a, **k: over_boundary_dt)

    result = parse_ru_datetime("30.07 16:00")

    assert result is None


def test_format_datetime_for_confirmation_prefixes_weekday_name():
    dt = datetime(2026, 7, 30, 16, 0)
    assert dt.weekday() == 3  # Thursday, verified independently via datetime.weekday()

    result = format_datetime_for_confirmation(dt)

    assert result == "четверг, " + format_datetime_for_display(dt)
    assert result == "четверг, 30 июля 2026, 16:00"


def test_format_datetime_for_confirmation_matches_display_for_another_weekday():
    dt = datetime(2026, 8, 15, 15, 0)
    assert dt.weekday() == 5  # Saturday

    result = format_datetime_for_confirmation(dt)

    assert result == "суббота, " + format_datetime_for_display(dt)


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


# --- build_reschedule_proposal_line ---

def test_build_reschedule_proposal_line_returns_none_when_no_proposal():
    appointment = _appointment(proposed_datetime=None)

    assert build_reschedule_proposal_line(appointment, viewer=CreatedBy.CLIENT) is None
    assert build_reschedule_proposal_line(appointment, viewer=CreatedBy.ADMIN) is None


def test_build_reschedule_proposal_line_client_viewer_own_proposal():
    appointment = _appointment(proposed_datetime="2026-08-15 15:00", proposed_by=CreatedBy.CLIENT)

    line = build_reschedule_proposal_line(appointment, viewer=CreatedBy.CLIENT)

    assert line == "Вы предложили перенос на: 15 августа 2026, 15:00"


def test_build_reschedule_proposal_line_client_viewer_admin_proposal():
    appointment = _appointment(proposed_datetime="2026-08-15 15:00", proposed_by=CreatedBy.ADMIN)

    line = build_reschedule_proposal_line(appointment, viewer=CreatedBy.CLIENT)

    assert line == "Клиника предложила перенос на: 15 августа 2026, 15:00"


def test_build_reschedule_proposal_line_admin_viewer_own_proposal():
    appointment = _appointment(proposed_datetime="2026-08-15 15:00", proposed_by=CreatedBy.ADMIN)

    line = build_reschedule_proposal_line(appointment, viewer=CreatedBy.ADMIN)

    assert line == "Вы предложили перенос на: 15 августа 2026, 15:00"


def test_build_reschedule_proposal_line_admin_viewer_client_proposal():
    appointment = _appointment(proposed_datetime="2026-08-15 15:00", proposed_by=CreatedBy.CLIENT)

    line = build_reschedule_proposal_line(appointment, viewer=CreatedBy.ADMIN)

    assert line == "Клиент предложил перенос на: 15 августа 2026, 15:00"


def test_build_reschedule_proposal_line_falls_back_to_raw_string_on_malformed_proposed_datetime():
    appointment = _appointment(proposed_datetime="not-a-real-datetime", proposed_by=CreatedBy.CLIENT)

    line = build_reschedule_proposal_line(appointment, viewer=CreatedBy.CLIENT)

    assert line == "Вы предложили перенос на: not-a-real-datetime"


def test_reschedule_negotiation_note_text():
    assert RESCHEDULE_NEGOTIATION_NOTE == "ℹ️ Ответить на предложение можно в уведомлении о переносе."
