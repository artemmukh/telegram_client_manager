from dataclasses import dataclass


@dataclass
class Record:
    user_id: int
    date_time: str
    description: str
    recommendation: str
    price: float
    status: str
    primary_id: int | None = None