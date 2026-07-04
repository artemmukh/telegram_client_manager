from dataclasses import dataclass


@dataclass
class Clinic:
    name: str
    clinic_id: int | None = None

