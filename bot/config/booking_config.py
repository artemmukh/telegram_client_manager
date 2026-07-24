"""Per-instance constants for the booking wizards (client self-booking and,
for MM, the admin slot-picker appointment creation flow).

These are intentionally hardcoded and not DB-driven yet (see
docs/client_functionality_vision.md section 1). A future pass will make
working hours/days configurable per clinic/doctor.

The active instance is resolved from the BOT_INSTANCE env var directly
(not via bot.config.config / bot.create_bot) to avoid a circular import
and to keep this module importable during test collection without a
real .env/BOT_TOKEN configured.
"""
import os
from datetime import datetime, timedelta

from bot.config.mm_data_parser_cfg import mm_cfg
from bot.config.zb_data_parser_cfg import zb_cfg

_instance = os.getenv("BOT_INSTANCE", "zb")
_cfg = {"zb": zb_cfg, "mm": mm_cfg}.get(_instance, zb_cfg)


def _generate_slots(cfg: dict) -> tuple[str, ...]:

    start = datetime.strptime(cfg.get("WORKING_HOURS_START"), "%H:%M")
    end = datetime.strptime(cfg.get("WORKING_HOURS_END"), "%H:%M")
    step = timedelta(minutes=cfg.get("SLOT_STEP_MINUTES"))

    if "BREAK_START" in cfg:
        break_start = datetime.strptime(cfg.get("BREAK_START"), "%H:%M")
        break_end = datetime.strptime(cfg.get("BREAK_END"), "%H:%M")

        slots = []
        current = start
        while current <= end:
            if break_start <= current < break_end:
                current += step
                continue
            slots.append(current.strftime("%H:%M"))
            current += step

        return tuple(slots)

    slots = []
    current = start
    while current <= end:
        slots.append(current.strftime("%H:%M"))
        current += step

    return tuple(slots)


WORKING_WEEKDAYS = _cfg["WORKING_WEEKDAYS"]
BOOKING_HORIZON_DAYS = _cfg["BOOKING_HORIZON_DAYS"]
MAX_PENDING_REQUESTS_PER_CLIENT = _cfg["MAX_PENDING_REQUESTS_PER_CLIENT"]
CANCELLATION_COOLDOWN_WINDOW_MINUTES = _cfg["CANCELLATION_COOLDOWN_WINDOW_MINUTES"]
MAX_CANCELLATIONS_PER_COOLDOWN_WINDOW = _cfg["MAX_CANCELLATIONS_PER_COOLDOWN_WINDOW"]
MAX_BOOKINGS_PER_SLOT = _cfg.get("MAX_BOOKINGS_PER_SLOT")

BOOKING_SLOTS = _generate_slots(_cfg)
