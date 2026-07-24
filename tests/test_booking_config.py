"""Tests for the instance-aware slot grid in bot/config/booking_config.py.

BOOKING_SLOTS/WORKING_WEEKDAYS/etc. are resolved once, at import time, from
os.getenv("BOT_INSTANCE", "zb") (see module docstring -- this is deliberate,
to avoid a circular import with bot.config.config / bot.create_bot and to
keep the module importable during test collection without a real .env).

Two things are covered:
1. _generate_slots(cfg) -- the pure slot-grid generator -- given zb_cfg and
   mm_cfg directly, since it needs no reload/env dance.
2. The BOT_INSTANCE -> BOOKING_SLOTS/WORKING_WEEKDAYS resolution itself, via
   monkeypatch.setenv + importlib.reload (no existing precedent for testing
   env-resolved config modules in this repo, so this establishes the
   pattern). Every reload is undone in a finally block so the module is left
   back at its zb default for any test collected after this one -- other
   modules that already did `from bot.config.booking_config import X` keep
   their own reference and are unaffected by the reload either way.
"""
import importlib

import pytest

import bot.config.booking_config as booking_config
from bot.config.mm_data_parser_cfg import mm_cfg
from bot.config.zb_data_parser_cfg import zb_cfg


def test_generate_slots_zb_grid_has_no_lunch_break():
    slots = booking_config._generate_slots(zb_cfg)

    assert slots == (
        "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30",
        "14:00", "14:30", "15:00", "15:30", "16:00", "16:30", "17:00", "17:30",
    )


def test_generate_slots_mm_grid_excludes_lunch_hour():
    slots = booking_config._generate_slots(mm_cfg)

    # BREAK_START is an inclusive bound and BREAK_END is exclusive in
    # _generate_slots (break_start <= current < break_end), so only the
    # 13:00 lunch slot is skipped; 14:00 remains bookable.
    assert "13:00" not in slots
    assert slots == (
        "09:00", "10:00", "11:00", "12:00", "14:00", "15:00", "16:00", "17:00", "18:00",
    )


@pytest.mark.parametrize(
    "instance, expected_first_slot, expected_last_slot",
    [("zb", "10:00", "17:30"), ("mm", "09:00", "18:00")],
)
def test_booking_slots_resolve_from_bot_instance_env_var(
    monkeypatch, instance, expected_first_slot, expected_last_slot,
):
    monkeypatch.setenv("BOT_INSTANCE", instance)
    try:
        reloaded = importlib.reload(booking_config)
        assert reloaded.BOOKING_SLOTS[0] == expected_first_slot
        assert reloaded.BOOKING_SLOTS[-1] == expected_last_slot
        assert reloaded.WORKING_WEEKDAYS == (0, 1, 2, 3, 4, 5)
    finally:
        monkeypatch.delenv("BOT_INSTANCE", raising=False)
        importlib.reload(booking_config)


def test_booking_slots_defaults_to_zb_grid_when_bot_instance_unset(monkeypatch):
    monkeypatch.delenv("BOT_INSTANCE", raising=False)

    reloaded = importlib.reload(booking_config)

    assert reloaded.BOOKING_SLOTS[0] == "10:00"
    assert reloaded.BOOKING_SLOTS[-1] == "17:30"


def test_booking_slots_falls_back_to_zb_for_unknown_instance(monkeypatch):
    monkeypatch.setenv("BOT_INSTANCE", "unknown-instance")
    try:
        reloaded = importlib.reload(booking_config)
        assert reloaded.BOOKING_SLOTS[0] == "10:00"
        assert reloaded.BOOKING_SLOTS[-1] == "17:30"
    finally:
        monkeypatch.delenv("BOT_INSTANCE", raising=False)
        importlib.reload(booking_config)
