from dataclasses import dataclass
from bot.utils.role import Role


@dataclass
class User:
    full_name: str
    phone: str
    role: Role
    telegram_user_id: int | None = None
    ID: int | None = None


