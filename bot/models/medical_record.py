from dataclasses import dataclass

from bot.utils.medical_record_enums import MedicalRecordStatus


@dataclass
class MedicalRecord:
    appointment_id: int
    status: MedicalRecordStatus
    id: int | None = None
    file_path: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    error_message: str | None = None
