from datetime import date, datetime

from bot.services.utils.date_parser import format_datetime_for_display


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
