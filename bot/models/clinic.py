from dataclasses import dataclass


@dataclass
class Clinic:
    name: str
    token: str
    clinic_id: int | None = None


