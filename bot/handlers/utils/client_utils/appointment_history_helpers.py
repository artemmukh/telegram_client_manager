from datetime import datetime

from bot.models.appointment import Appointment
from bot.services.utils.date_parser import format_datetime_for_display
from bot.utils.appointment_enums import AppointmentStatus

HISTORY_STATUS_LABELS = {
    AppointmentStatus.PENDING: "🕐 ожидает",
    AppointmentStatus.CONFIRMED: "✅ подтверждена",
    AppointmentStatus.CANCELLED: "❌ отменена",
    AppointmentStatus.COMPLETED: "✔️ завершена",
    AppointmentStatus.NO_SHOW: "🙅 неявка",
}


def _format_appointment_datetime(appointment: Appointment) -> str:
    try:
        return format_datetime_for_display(datetime.fromisoformat(appointment.datetime))
    except ValueError:
        return appointment.datetime


def build_history_button_text(appointment: Appointment) -> str:
    status_label = HISTORY_STATUS_LABELS.get(appointment.status, appointment.status.value)
    status_emoji = status_label.split()[0]
    display_datetime = _format_appointment_datetime(appointment)
    return f"{status_emoji} {display_datetime}"


def build_history_card_text(appointment: Appointment) -> str:
    display_datetime = _format_appointment_datetime(appointment)

    lines = [f"Дата и время: {display_datetime}"]

    if appointment.purpose:
        lines.append(f"Услуга: {appointment.purpose}")

    lines.append(f"Статус: {HISTORY_STATUS_LABELS.get(appointment.status, appointment.status.value)}")

    lines.append(f"Клиника: {appointment.clinic_name or 'Информация не доступна'}")

    return "\n".join(lines)
