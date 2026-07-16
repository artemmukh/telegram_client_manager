from dataclasses import dataclass
from bot.utils.role import Role


@dataclass
class User:
    full_name: str
    phone: str
    role: Role
    telegram_user_id: int | None = None
    ID: int | None = None
    clinic_id: int | None = None
    clinic_name: str | None = None
    reminder_24h: bool = True
    reminder_2h: bool = True
    pending_full_name: str | None = None
    created_at: str | None = None


