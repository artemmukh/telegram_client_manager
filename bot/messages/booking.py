from datetime import date, datetime

from bot.services.utils.date_parser import format_datetime_for_display

NO_AVAILABLE_STAFF = "В вашей клинике сейчас нет доступных врачей для записи."
CHOOSE_SPECIALIST = "Выберите специалиста:"
CHOOSE_DAY = "Выберите день записи:"
DEFAULT_STAFF_NAME_FALLBACK = "Специалист"
INVALID_DATE = "Некорректная дата, попробуйте ещё раз."
NO_SLOTS_FOR_DAY = "На этот день больше нет доступных слотов."
INVALID_TIME = "Некорректное время, попробуйте ещё раз."
COMPLAINT_PROMPT = "Опишите жалобу или причину визита (от 2 до 100 символов):"
SUBMITTED = "✅ Заявка отправлена. Ожидайте подтверждения от клиники."

BACK_TO_APPOINTMENTS_MENU = "⬅️ К меню записей"

BOOKING_CANCEL_KB_CANCEL = "❌ Отмена"
BOOKING_DOCTOR_KB_CANCEL = "❌ Отмена"
BOOKING_DAY_KB_CANCEL = "❌ Отмена"
BOOKING_DAY_KB_BACK = "⬅️ Назад"
BOOKING_DAY_KB_FORWARD = "➡️ Дальше"
BOOKING_SLOT_KB_CANCEL = "❌ Отмена"
BOOKING_CONFIRM_KB_SUBMIT = "✅ Отправить"
BOOKING_CONFIRM_KB_RESTART = "✏️ Изменить"
BOOKING_CONFIRM_KB_CANCEL = "❌ Отмена"


def choose_time_prompt(day: date) -> str:
    return f"Выберите время на {day.strftime('%d.%m.%Y')}:"


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
