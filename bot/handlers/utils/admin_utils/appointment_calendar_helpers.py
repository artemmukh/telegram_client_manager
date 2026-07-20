from calendar import monthrange
from datetime import datetime

CALENDAR_MIN_YEAR = 2026
CALENDAR_MAX_YEAR = 2027

_MONTH_NAMES_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}

WEEKDAY_LABELS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def clamp_month_to_range(year: int, month: int) -> tuple[int, int]:
    """Clamp (year, month) into the fixed 2026-2027 calendar range.

    Falls back to the nearest boundary month when outside the range,
    and also clamps an out-of-1-12 month magnitude before applying
    the year-range check.
    """
    month = max(1, min(12, month))
    if year < CALENDAR_MIN_YEAR:
        return CALENDAR_MIN_YEAR, 1
    if year > CALENDAR_MAX_YEAR:
        return CALENDAR_MAX_YEAR, 12
    return year, month


def clamp_calendar_date(year: int, month: int, day: int) -> tuple[int, int, int]:
    """Clamp (year, month, day) into the fixed 2026-2027 calendar range.

    Reuses clamp_month_to_range for year/month, then clamps day into the
    valid [1, N] range for that (already-clamped) month.
    """
    year, month = clamp_month_to_range(year, month)
    _, days_in_month = monthrange(year, month)
    day = max(1, min(days_in_month, day))
    return year, month, day


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


def get_month_grid(year: int, month: int) -> list[tuple[int, int, int]]:
    """Build a Monday-first calendar grid, padded to full weeks with adjacent-month days."""
    first_weekday = datetime(year, month, 1).weekday()

    prev_month, prev_year = month - 1, year
    if prev_month < 1:
        prev_month, prev_year = 12, year - 1

    next_month, next_year = month + 1, year
    if next_month > 12:
        next_month, next_year = 1, year + 1

    _, days_in_prev_month = monthrange(prev_year, prev_month)
    leading = [(d, prev_year, prev_month) for d in range(days_in_prev_month - first_weekday + 1, days_in_prev_month + 1)]
    current = [(d, year, month) for d in generate_month_days(year, month)]

    grid = leading + current
    trailing_day = 1
    while len(grid) % 7 != 0:
        grid.append((trailing_day, next_year, next_month))
        trailing_day += 1

    return grid


def format_month_label(year: int, month: int) -> str:
    """Format a non-interactive 'Месяц Год' label, e.g. 'Июль 2026'."""
    return f"{_MONTH_NAMES_RU[month]} {year}"


def format_calendar_date_display(date_str: str) -> str:
    """Format an ISO 'YYYY-MM-DD' date string for display, e.g. '17.07.2026'."""
    return datetime.fromisoformat(date_str).strftime("%d.%m.%Y")
