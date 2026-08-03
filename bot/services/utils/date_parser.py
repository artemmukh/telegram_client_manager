from datetime import datetime
from typing import Optional
import pytz

import dateparser
import re

from bot.models.appointment import Appointment
from bot.utils.appointment_enums import CreatedBy

_RESCHEDULE_NEGOTIATION_NOTE = {
    "ru": "ℹ️ Ответить на предложение можно в уведомлении о переносе.",
    "uz": "ℹ️ Taklifga ko'chirish haqidagi bildirishnomada javob berishingiz mumkin.",
}


def reschedule_negotiation_note(lang: str = "ru") -> str:
    return _RESCHEDULE_NEGOTIATION_NOTE.get(lang, _RESCHEDULE_NEGOTIATION_NOTE["ru"])

MAX_YEARS_AHEAD = 1

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

    text = text.strip()
    if len(text) > 50:
        return None

    normalized = _normalize_colloquial_time(text)
    now = get_current_tashkent_datetime()

    parsed = dateparser.parse(
        normalized,
        languages=['ru'],
        date_formats=['%d.%m.%y %H:%M', '%d.%m.%y %H.%M', '%d.%m.%Y %H:%M', '%d.%m.%Y %H.%M'],
        settings={
            'PREFER_DATES_FROM': 'future',
            'TIMEZONE': 'Asia/Tashkent',
            'RETURN_AS_TIMEZONE_AWARE': True,
            'STRICT_PARSING': False,
            'RELATIVE_BASE': now,
        }
    )

    if parsed is not None and parsed.year > now.year + MAX_YEARS_AHEAD:
        return None

    return parsed


_MONTH_NAMES_GENITIVE_RU = {
    1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля',
    5: 'мая', 6: 'июня', 7: 'июля', 8: 'августа',
    9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря'
}

# Uzbek month names don't inflect by grammatical case, so the same forms
# used for calendar headers (appointment_calendar_helpers._MONTH_NAMES_UZ)
# apply here too. Duplicated as a literal rather than imported, since this
# is a Service module and appointment_calendar_helpers.py is a Handler-layer
# module -- importing it would invert the Handler -> Service dependency
# direction mandated by CLAUDE.md.
_MONTH_NAMES_UZ = {
    1: "Yanvar", 2: "Fevral", 3: "Mart", 4: "Aprel",
    5: "May", 6: "Iyun", 7: "Iyul", 8: "Avgust",
    9: "Sentabr", 10: "Oktabr", 11: "Noyabr", 12: "Dekabr",
}

_MONTH_NAMES_GENITIVE = {"ru": _MONTH_NAMES_GENITIVE_RU, "uz": _MONTH_NAMES_UZ}

_WEEKDAYS_FULL = {
    "ru": {0: 'понедельник', 1: 'вторник', 2: 'среда', 3: 'четверг', 4: 'пятница', 5: 'суббота', 6: 'воскресенье'},
    "uz": {0: 'Dushanba', 1: 'Seshanba', 2: 'Chorshanba', 3: 'Payshanba', 4: 'Juma', 5: 'Shanba', 6: 'Yakshanba'},
}


def format_datetime_for_display(dt: datetime, lang: str = "ru") -> str:
    """
    Format datetime for display to user.

    Example (ru): "15 сентября 2026, 15:00"
    Example (uz): "15 Sentabr 2026, 15:00"
    """
    months = _MONTH_NAMES_GENITIVE.get(lang, _MONTH_NAMES_GENITIVE["ru"])
    month_name = months.get(dt.month, '')
    return f"{dt.day} {month_name} {dt.year}, {dt.hour:02d}:{dt.minute:02d}"


def format_datetime_for_confirmation(dt: datetime, lang: str = "ru") -> str:
    """
    Format datetime for the "did you mean" confirmation screen, with the
    weekday name prefixed.

    Example (ru): "четверг, 30 июля 2026, 16:00"
    Example (uz): "Payshanba, 30 iyul 2026, 16:00"
    """
    weekdays = _WEEKDAYS_FULL.get(lang, _WEEKDAYS_FULL["ru"])
    weekday_name = weekdays[dt.weekday()]
    return f"{weekday_name}, {format_datetime_for_display(dt, lang)}"


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


_YOU_PROPOSED_RESCHEDULE = {
    "ru": "Вы предложили перенос на: {proposed_display}",
    "uz": "Siz {proposed_display} vaqtiga ko'chirishni taklif qildingiz",
}

_CLINIC_PROPOSED_RESCHEDULE = {
    "ru": "Клиника предложила перенос на: {proposed_display}",
    "uz": "Klinika {proposed_display} vaqtiga ko'chirishni taklif qildi",
}

_CLIENT_PROPOSED_RESCHEDULE = {
    "ru": "Клиент предложил перенос на: {proposed_display}",
    "uz": "Mijoz {proposed_display} vaqtiga ko'chirishni taklif qildi",
}


def build_reschedule_proposal_line(appointment: Appointment, viewer: CreatedBy, lang: str = "ru") -> str | None:
    """Build the "X predlozhil perenos na: ..." line shown to `viewer` when a
    reschedule negotiation is in progress, or None if there is no proposal.
    """
    if appointment.proposed_datetime is None:
        return None

    try:
        proposed_display = format_datetime_for_display(datetime.fromisoformat(appointment.proposed_datetime), lang)
    except ValueError:
        proposed_display = appointment.proposed_datetime

    if appointment.proposed_by == viewer:
        template = _YOU_PROPOSED_RESCHEDULE
    elif viewer == CreatedBy.CLIENT:
        template = _CLINIC_PROPOSED_RESCHEDULE
    else:
        template = _CLIENT_PROPOSED_RESCHEDULE

    return template.get(lang, template["ru"]).format(proposed_display=proposed_display)
