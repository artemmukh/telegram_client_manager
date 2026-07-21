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
    status_updated_at: str | None = None
    id: int | None = None
    clinic_name: str | None = None
    created_by_telegram_id: int | None = None
    client_full_name: str | None = None
    client_phone: str | None = None
    notification_message_id: int | None = None
    proposed_datetime: str | None = None
    proposal_message_id: int | None = None
    proposed_by: CreatedBy | None = None
    admin_notification_message_id: int | None = None
    doctor_full_name: str | None = None
    doctor_phone: str | None = None
    doctor_is_doctor: bool | None = None
    price: float | None = None
    decided_by_user_id: int | None = None
