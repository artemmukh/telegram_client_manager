from datetime import datetime

from bot.models.appointment import Appointment
from bot.services.utils.date_parser import format_datetime_for_display
from bot.utils.appointment_enums import APPOINTMENT_STATUS_LABELS, CreatedBy

HISTORY_STATUS_LABELS = APPOINTMENT_STATUS_LABELS


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

    if appointment.proposed_datetime:
        try:
            proposed_display = format_datetime_for_display(datetime.fromisoformat(appointment.proposed_datetime))
        except ValueError:
            proposed_display = appointment.proposed_datetime

        if appointment.proposed_by == CreatedBy.CLIENT:
            lines.append(f"Вы предложили перенос на: {proposed_display}")
        else:
            lines.append(f"Клиника предложила перенос на: {proposed_display}")

    lines.append(f"Статус: {HISTORY_STATUS_LABELS.get(appointment.status, appointment.status.value)}")

    lines.append(f"Клиника: {appointment.clinic_name or 'Информация не доступна'}")

    if appointment.doctor_full_name:
        lines.append(f"Врач: {appointment.doctor_full_name}")
        lines.append(f"Телефон врача: {appointment.doctor_phone or '—'}")

    return "\n".join(lines)
