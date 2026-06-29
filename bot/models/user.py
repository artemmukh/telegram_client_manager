from dataclasses import dataclass

@dataclass
class User:
    telegram_user_id: int
    full_name: str
    phone: str
    role: str
    is_registered: bool
    primary_id: int | None = None