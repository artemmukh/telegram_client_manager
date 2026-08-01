from dataclasses import dataclass


@dataclass
class UserSettings:
    user_id: int
    reminder_24h: bool = True
    reminder_2h: bool = True
    language: str = "ru"
