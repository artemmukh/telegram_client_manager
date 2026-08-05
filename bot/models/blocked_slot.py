from dataclasses import dataclass


@dataclass
class BlockedSlot:
    clinic_id: int
    start_datetime: str
    end_datetime: str
    reason: str
    created_by: int
    id: int | None = None
    staff_id: int | None = None
    created_at: str | None = None
    cancelled_at: str | None = None
