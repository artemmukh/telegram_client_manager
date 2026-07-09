from bot.handlers.utils.admin_utils.client_browser_helpers import (
    edit_tracked_message,
    remember_tracked_message,
)
from bot.models.appointment import Appointment

__all__ = [
    "build_appointment_button_text",
    "edit_tracked_message",
    "remember_tracked_message",
]


def build_appointment_button_text(appointment: Appointment) -> str:
    client_name = appointment.client_full_name or "Без имени"
    return f"📅 {client_name} · {appointment.datetime}"
