from dataclasses import dataclass


@dataclass
class Record:
    user_id: int
    date_time: str
    description: str
    recommendation: str
    price: float
    clinic_id: int
    clinic_name: str
    status: str
    id: int | None = None

