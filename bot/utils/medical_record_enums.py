from enum import Enum


class MedicalRecordStatus(Enum):
    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    READY_PARTIAL = "ready_partial"
    FAILED = "failed"
