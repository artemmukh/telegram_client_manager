from datetime import date, datetime, timedelta

from bot.config.booking_config import BOOKING_HORIZON_DAYS, BOOKING_SLOTS, WORKING_WEEKDAYS
from bot.services.utils.date_parser import format_datetime_for_display


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


def find_first_available_week_offset(reference_date: date, max_offset: int = 3) -> int:
    """Return the earliest week_offset (starting from 0) that yields working days.

    Needed because week_offset=0 can be empty (e.g. reference_date is a Sunday,
    since Mon-Sat of that same week all fall before reference_date).
    """
    for offset in range(max_offset + 1):
        if generate_working_days(reference_date, offset):
            return offset

    return 0


def generate_available_slots(day: date, now: datetime) -> list[str]:
    """Return the fixed slot grid for the given day.

    For today, slots that already passed relative to `now` are filtered out.
    Future days return the full slot grid. No availability/conflict checking.
    """
    if day != now.date():
        return list(BOOKING_SLOTS)

    current_time = now.time()
    return [slot for slot in BOOKING_SLOTS if datetime.strptime(slot, "%H:%M").time() > current_time]


def build_booking_confirmation_text(
    doctor_name: str, day: date, slot: str, complaint: str, clinic_name: str | None
) -> str:
    slot_time = datetime.strptime(slot, "%H:%M").time()
    display_datetime = format_datetime_for_display(datetime.combine(day, slot_time))

    return (
        "Проверьте данные записи:\n\n"
        f"👨‍⚕️ Специалист: {doctor_name}\n"
        f"📅 Дата и время: {display_datetime}\n"
        f"📝 Жалоба: {complaint}\n"
        f"🏥 Клиника: {clinic_name or 'Информация не доступна'}\n\n"
        "Отправить заявку на запись?"
    )
