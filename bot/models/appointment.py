from dataclasses import dataclass

from bot.utils.appointment_enums import AppointmentStatus, CreatedBy


@dataclass
class Appointment:
    clinic_id: int
    client_id: int
    datetime: str
    purpose: str
    created_by: CreatedBy
    status: AppointmentStatus
    doctor_id: int | None = None
    created_at: str | None = None
    id: int | None = None
    clinic_name: str | None = None
    created_by_telegram_id: int | None = None
    client_full_name: str | None = None
    client_phone: str | None = None
    notification_message_id: int | None = None
