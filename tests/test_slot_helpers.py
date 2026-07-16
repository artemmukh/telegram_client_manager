from datetime import date, datetime

from bot.config.booking_config import BOOKING_SLOTS
from bot.services.utils.slot_helpers import generate_available_slots


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
