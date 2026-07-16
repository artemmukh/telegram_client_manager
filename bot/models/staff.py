from dataclasses import dataclass


@dataclass
class Staff:
    telegram_user_id: int
    clinic_id: int
    visibility_scope: str | None = None