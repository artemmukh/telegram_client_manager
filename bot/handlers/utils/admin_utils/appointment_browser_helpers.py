from bot.handlers.utils.admin_utils.client_browser_helpers import (
    edit_tracked_message,
    remember_tracked_message,
)
from bot.models.appointment import Appointment
from bot.utils.tools import format_phone_short

__all__ = [
    "build_appointment_button_text",
    "edit_tracked_message",
    "remember_tracked_message",
]


def build_appointment_button_text(appointment: Appointment) -> str:
    client_name = appointment.client_full_name or "Без имени"
    phone = format_phone_short(appointment.client_phone) if appointment.client_phone else "—"
    return f"📅 {client_name} · {phone} · {appointment.datetime}"
