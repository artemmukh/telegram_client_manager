from datetime import date, datetime

from bot.config.booking_config import BOOKING_HORIZON_DAYS, BOOKING_SLOTS
from bot.handlers.utils.client_utils.booking_helpers import (
    build_booking_confirmation_text,
    find_first_available_week_offset,
    generate_available_slots,
    generate_working_days,
)


def test_generate_working_days_skips_sunday():
    # 2026-07-06 is a Monday
    reference = date(2026, 7, 6)

    days = generate_working_days(reference, week_offset=0)

    assert days == [
        date(2026, 7, 6), date(2026, 7, 7), date(2026, 7, 8),
        date(2026, 7, 9), date(2026, 7, 10), date(2026, 7, 11),
    ]
    assert date(2026, 7, 12) not in days  # Sunday


def test_generate_working_days_excludes_days_before_reference():
    # 2026-07-09 is a Thursday
    reference = date(2026, 7, 9)

    days = generate_working_days(reference, week_offset=0)

    assert min(days) == reference
    assert date(2026, 7, 6) not in days
    assert date(2026, 7, 7) not in days
    assert date(2026, 7, 8) not in days


def test_generate_working_days_clamps_to_horizon():
    reference = date(2026, 7, 6)
    horizon_end = reference.toordinal() + BOOKING_HORIZON_DAYS

    days = generate_working_days(reference, week_offset=2)

    assert all(day.toordinal() <= horizon_end for day in days)


def test_generate_working_days_returns_empty_beyond_horizon():
    reference = date(2026, 7, 6)

    days = generate_working_days(reference, week_offset=10)

    assert days == []


def test_find_first_available_week_offset_returns_zero_when_week0_has_days():
    reference = date(2026, 7, 6)  # Monday

    assert find_first_available_week_offset(reference) == 0


def test_find_first_available_week_offset_skips_empty_first_week_on_sunday():
    reference = date(2026, 7, 12)  # Sunday, week0 has no valid days

    offset = find_first_available_week_offset(reference)

    assert offset > 0
    assert generate_working_days(reference, offset) != []


def test_generate_available_slots_returns_full_grid_for_future_day():
    future_day = date(2026, 7, 20)
    now = datetime(2026, 7, 10, 12, 0)

    slots = generate_available_slots(future_day, now)

    assert slots == list(BOOKING_SLOTS)


def test_generate_available_slots_filters_past_slots_for_today():
    today = date(2026, 7, 10)
    now = datetime(2026, 7, 10, 13, 15)

    slots = generate_available_slots(today, now)

    assert "10:30" not in slots
    assert "13:00" not in slots
    assert "13:30" in slots
    assert slots == [s for s in BOOKING_SLOTS if s > "13:15"]


def test_generate_available_slots_empty_when_all_passed_today():
    today = date(2026, 7, 10)
    now = datetime(2026, 7, 10, 23, 0)

    slots = generate_available_slots(today, now)

    assert slots == []


def test_build_booking_confirmation_text_contains_key_fields():
    text = build_booking_confirmation_text(
        doctor_name="Иванов Иван",
        day=date(2026, 7, 10),
        slot="14:30",
        complaint="Болит зуб",
        clinic_name="Зуб Мудрости",
    )

    assert "Иванов Иван" in text
    assert "Болит зуб" in text
    assert "Зуб Мудрости" in text


def test_build_booking_confirmation_text_handles_missing_clinic_name():
    text = build_booking_confirmation_text(
        doctor_name="Иванов Иван",
        day=date(2026, 7, 10),
        slot="14:30",
        complaint="Болит зуб",
        clinic_name=None,
    )

    assert "Информация не доступна" in text
