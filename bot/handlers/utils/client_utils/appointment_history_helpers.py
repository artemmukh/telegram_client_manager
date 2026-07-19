from datetime import datetime

from bot.models.appointment import Appointment
from bot.services.utils.date_parser import build_reschedule_proposal_line, format_datetime_for_display
from bot.utils.appointment_enums import APPOINTMENT_STATUS_LABELS, AppointmentStatus, CreatedBy

HISTORY_STATUS_LABELS = APPOINTMENT_STATUS_LABELS


def _format_appointment_datetime(appointment: Appointment) -> str:
    try:
        return format_datetime_for_display(datetime.fromisoformat(appointment.datetime))
    except ValueError:
        return appointment.datetime


def _is_negotiating(appointment: Appointment) -> bool:
    return appointment.status == AppointmentStatus.CONFIRMED and appointment.proposed_datetime is not None


def build_history_button_text(appointment: Appointment) -> str:
    status_label = HISTORY_STATUS_LABELS.get(appointment.status, appointment.status.value)
    status_emoji = status_label.split()[0]
    display_datetime = _format_appointment_datetime(appointment)
    marker = "🔁" if _is_negotiating(appointment) else ""
    return f"{marker}{status_emoji} {display_datetime}"


def build_history_card_text(appointment: Appointment) -> str:
    display_datetime = _format_appointment_datetime(appointment)

    lines = [f"Дата и время: {display_datetime}"]

    if appointment.purpose:
        lines.append(f"Услуга: {appointment.purpose}")

    proposal_line = build_reschedule_proposal_line(appointment, viewer=CreatedBy.CLIENT)
    if proposal_line is not None:
        lines.append(proposal_line)

    lines.append(f"Статус: {HISTORY_STATUS_LABELS.get(appointment.status, appointment.status.value)}")

    lines.append(f"Клиника: {appointment.clinic_name or 'Информация не доступна'}")

    if appointment.doctor_full_name and appointment.doctor_is_doctor:
        lines.append(f"Врач: {appointment.doctor_full_name}")
        lines.append(f"Телефон врача: {appointment.doctor_phone or '—'}")

    return "\n".join(lines)
