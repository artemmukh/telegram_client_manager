from calendar import monthrange
from datetime import datetime

CALENDAR_MIN_YEAR = 2026
CALENDAR_MAX_YEAR = 2027

_MONTH_NAMES_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}


def clamp_month_to_range(year: int, month: int) -> tuple[int, int]:
    """Clamp (year, month) into the fixed 2026-2027 calendar range.

    Falls back to the nearest boundary month when outside the range.
    """
    if year < CALENDAR_MIN_YEAR:
        return CALENDAR_MIN_YEAR, 1
    if year > CALENDAR_MAX_YEAR:
        return CALENDAR_MAX_YEAR, 12
    return year, month


def shift_month(year: int, month: int, direction: str) -> tuple[int, int]:
    """Move one month forward/backward, wrapping circularly within 2026-2027."""
    if direction == "next":
        month += 1
        if month > 12:
            month = 1
            year += 1
    elif direction == "prev":
        month -= 1
        if month < 1:
            month = 12
            year -= 1
    else:
        raise ValueError(f"Unknown direction: {direction}")

    if year > CALENDAR_MAX_YEAR:
        return CALENDAR_MIN_YEAR, 1
    if year < CALENDAR_MIN_YEAR:
        return CALENDAR_MAX_YEAR, 12

    return year, month


def generate_month_days(year: int, month: int) -> list[int]:
    """Return [1, ..., N] for the number of days in the given month."""
    _, days_in_month = monthrange(year, month)
    return list(range(1, days_in_month + 1))


def format_month_label(year: int, month: int) -> str:
    """Format a non-interactive 'Месяц Год' label, e.g. 'Июль 2026'."""
    return f"{_MONTH_NAMES_RU[month]} {year}"


def format_calendar_date_display(date_str: str) -> str:
    """Format an ISO 'YYYY-MM-DD' date string for display, e.g. '17.07.2026'."""
    return datetime.fromisoformat(date_str).strftime("%d.%m.%Y")
