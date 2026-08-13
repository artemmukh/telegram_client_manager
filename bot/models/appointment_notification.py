from dataclasses import dataclass


@dataclass
class AppointmentNotification:
    appointment_id: int
    chat_id: int
    message_id: int
    kind: str
    id: int | None = None
    created_at: str | None = None
    compact_text: str | None = None
