from datetime import datetime
from typing import Optional
import pytz

import dateparser
import re

from bot.models.appointment import Appointment
from bot.utils.appointment_enums import CreatedBy

RESCHEDULE_NEGOTIATION_NOTE = "ℹ️ Ответить на предложение можно в уведомлении о переносе."

# 'в 4 часов' по умолчанию трактуется dateparser'ом либо как 4 утра,
# либо вообще как "4-е число месяца". Нормализуем вручную под контекст
# клиники: рабочий день днём/вечером, поэтому маленькие часы без
# уточнения (1-8) считаем послеобеденными.
_TIME_WORD_RE = re.compile(
    r'(?<!через\s)\bв\s+(\d{1,2})\s*(?:час(?:а|ов)?)?\s*(утра|дня|вечера|ночи)?\b(?!\s*[:.]\s*\d)',
    re.IGNORECASE,
)


def _normalize_colloquial_time(text: str) -> str:
    def repl(m: re.Match) -> str:
        hour = int(m.group(1))
        period = (m.group(2) or '').lower()

        if period in ('дня', 'вечера'):
            if hour < 12:
                hour += 12
        elif period == 'ночи':
            if hour == 12:
                hour = 0
            elif hour >= 10:          # 10, 11 ночи -> 22:00, 23:00
                hour += 12
            # 1-9 ночи остаются как есть (раннее утро)
        elif period == 'утра':
            pass                      # уже корректно как есть
        else:
            # без уточнения: маленькие часы (1-8) считаем послеобеденными
            if 1 <= hour <= 8:
                hour += 12

        return f"{hour:02d}:00"

    return _TIME_WORD_RE.sub(repl, text)


def parse_ru_datetime(text: str) -> Optional[datetime]:
    if not text or not text.strip():
        return None

    normalized = _normalize_colloquial_time(text.strip())

    return dateparser.parse(
        normalized,
        languages=['ru'],
        date_formats=['%d.%m.%y %H:%M', '%d.%m.%y %H.%M', '%d.%m.%Y %H:%M', '%d.%m.%Y %H.%M'],
        settings={
            'PREFER_DATES_FROM': 'future',
            'TIMEZONE': 'Asia/Tashkent',
            'RETURN_AS_TIMEZONE_AWARE': True,
            'STRICT_PARSING': False,
        }
    )


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


def format_appointment_card_datetime(appointment_time: str) -> str:
    """
    Format a stored appointment datetime for display in the appointment card.

    Example: "2026-07-16 14:30:00" -> "16.07.2026 14:30"
    """
    try:
        dt = datetime.fromisoformat(appointment_time)
    except ValueError:
        return appointment_time

    return dt.strftime("%d.%m.%Y %H:%M")


def format_datetime_for_db(dt: datetime) -> str:
    """
    Format datetime for database storage (strips timezone information).

    Returns: YYYY-MM-DD HH:MM format string
    """
    return dt.strftime("%Y-%m-%d %H:%M")


def get_current_tashkent_time() -> str:
    """
    Get current time in Asia/Tashkent timezone formatted for database storage.

    Returns: YYYY-MM-DD HH:MM:SS format string
    """
    tz = pytz.timezone('Asia/Tashkent')
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S")


def get_current_tashkent_datetime() -> datetime:
    """Current time in Asia/Tashkent as a naive datetime, comparable to appointment.datetime."""
    return datetime.now(pytz.timezone("Asia/Tashkent")).replace(tzinfo=None)


def is_appointment_upcoming(appointment: Appointment, now: datetime) -> bool:
    """
    Whether the appointment's relevant datetime (proposed_datetime if present,
    otherwise datetime) is not before `now`.

    Returns False if the relevant datetime cannot be parsed.
    """
    relevant_datetime = (
        appointment.proposed_datetime
        if appointment.proposed_datetime is not None
        else appointment.datetime
    )

    try:
        appointment_dt = datetime.fromisoformat(relevant_datetime)
    except ValueError:
        return False

    return appointment_dt >= now


def build_reschedule_proposal_line(appointment: Appointment, viewer: CreatedBy) -> str | None:
    """Build the "X predlozhil perenos na: ..." line shown to `viewer` when a
    reschedule negotiation is in progress, or None if there is no proposal.
    """
    if appointment.proposed_datetime is None:
        return None

    try:
        proposed_display = format_datetime_for_display(datetime.fromisoformat(appointment.proposed_datetime))
    except ValueError:
        proposed_display = appointment.proposed_datetime

    if appointment.proposed_by == viewer:
        return f"Вы предложили перенос на: {proposed_display}"
    if viewer == CreatedBy.CLIENT:
        return f"Клиника предложила перенос на: {proposed_display}"
    return f"Клиент предложил перенос на: {proposed_display}"
