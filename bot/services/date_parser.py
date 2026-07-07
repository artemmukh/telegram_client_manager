from datetime import datetime
from typing import Optional

import dateparser


def parse_ru_datetime(text: str) -> Optional[datetime]:
    """
    Parse Russian natural language datetime.

    Supports formats like:
    - "завтра в 3 часа" (tomorrow at 3 o'clock)
    - "13 сентября 15:30" (September 13 at 15:30)
    - "в понедельник в 14:00" (Monday at 14:00)
    - "через 2 часа" (in 2 hours)
    - "сегодня в 18:00" (today at 18:00)

    Args:
        text: Natural language datetime string in Russian

    Returns:
        Parsed datetime with Asia/Tashkent timezone, or None if parsing failed
    """
    if not text or not text.strip():
        return None

    parsed = dateparser.parse(
        text,
        languages=['ru'],
        settings={
            'PREFER_DATES_FROM': 'future',
            'TIMEZONE': 'Asia/Tashkent',
            'RETURN_AS_TIMEZONE_AWARE': True,
            'STRICT_PARSING': False,
        }
    )

    return parsed


def format_datetime_for_display(dt: datetime) -> str:
    """
    Format datetime for display to user.

    Example: "15 сентября 2026, 15:00"
    """
    months = {
        1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля',
        5: 'мая', 6: 'июня', 7: 'июля', 8: 'августа',
        9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря'
    }
    month_name = months.get(dt.month, '')
    return f"{dt.day} {month_name} {dt.year}, {dt.hour:02d}:{dt.minute:02d}"


def format_datetime_for_db(dt: datetime) -> str:
    """
    Format datetime for database storage (strips timezone information).

    Returns: YYYY-MM-DD HH:MM format string
    """
    return dt.strftime("%Y-%m-%d %H:%M")
