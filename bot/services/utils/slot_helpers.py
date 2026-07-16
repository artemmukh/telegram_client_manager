from datetime import date, datetime

from bot.config.booking_config import BOOKING_SLOTS


def generate_available_slots(day: date, now: datetime) -> list[str]:
    """Return the fixed slot grid for the given day.

    For today, slots that already passed relative to `now` are filtered out.
    Future days return the full slot grid. No availability/conflict checking.
    """
    if day != now.date():
        return list(BOOKING_SLOTS)

    current_time = now.time()
    return [slot for slot in BOOKING_SLOTS if datetime.strptime(slot, "%H:%M").time() > current_time]
