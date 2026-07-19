import re
from datetime import datetime

from bot.handlers.utils.admin_utils.client_browser_helpers import (
    edit_tracked_message,
    remember_tracked_message,
)
from bot.models.appointment import Appointment
from bot.utils.appointment_enums import AppointmentStatus

__all__ = [
    "build_appointment_button_text",
    "format_appointment_button",
    "edit_tracked_message",
    "remember_tracked_message",
]


def format_appointment_button(full_name: str, phone: str, appointment_time: str) -> str:
    name_parts = full_name.split()
    given_name = name_parts[1] if len(name_parts) >= 2 else full_name

    digits = re.sub(r"\D", "", phone)
    phone_display = digits[-9:] if len(digits) >= 9 else phone

    try:
        dt = datetime.fromisoformat(appointment_time)
        datetime_display = f"{dt.strftime('%d.%m')} • {dt.strftime('%H:%M')}"
    except ValueError:
        datetime_display = appointment_time

    return f"{datetime_display} • {given_name} • {phone_display}"


def build_appointment_button_text(appointment: Appointment) -> str:
    client_name = appointment.client_full_name or "Безымянный"
    phone = appointment.client_phone or "—"
    text = format_appointment_button(client_name, phone, appointment.datetime)

    if appointment.status == AppointmentStatus.CONFIRMED and appointment.proposed_datetime is not None:
        return f"🔁 {text}"

    return text
