import math
from datetime import date, timedelta

from bot.config.booking_config import BOOKING_HORIZON_DAYS, WORKING_WEEKDAYS


def generate_working_days(reference_date: date, week_offset: int) -> list[date]:
    """Return up to 6 working dates (Mon-Sat) for the given week offset.

    Dates are clamped to the range [reference_date, reference_date + BOOKING_HORIZON_DAYS].
    Returns an empty list if the requested week is entirely outside that range.
    """
    horizon_end = reference_date + timedelta(days=BOOKING_HORIZON_DAYS)
    week_start = reference_date - timedelta(days=reference_date.weekday()) + timedelta(weeks=week_offset)

    days = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        if day.weekday() not in WORKING_WEEKDAYS:
            continue
        if day < reference_date or day > horizon_end:
            continue
        days.append(day)

    return days


def find_first_available_week_offset(
    reference_date: date, max_offset: int = math.ceil(BOOKING_HORIZON_DAYS / 7) + 1
) -> int:
    """Return the earliest week_offset (starting from 0) that yields working days.

    Needed because week_offset=0 can be empty (e.g. reference_date is a Sunday,
    since Mon-Sat of that same week all fall before reference_date).
    """
    for offset in range(max_offset + 1):
        if generate_working_days(reference_date, offset):
            return offset

    return 0
