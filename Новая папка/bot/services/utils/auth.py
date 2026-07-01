from bot.config.config import admin_ids
from bot.utils.role import Role


class AuthService:

    @staticmethod
    def detect_role(telegram_user_id: int) -> Role:
        if telegram_user_id in admin_ids:
            return Role.ADMIN
        return Role.CLIENT
