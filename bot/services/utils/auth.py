from bot.config.config import load_config
from bot.utils.role import Role


class AuthService:

    @staticmethod
    def detect_role(telegram_user_id: int) -> Role:
        admin_ids = load_config().admin_ids
        if telegram_user_id in admin_ids:
            return Role.ADMIN
        return Role.CLIENT
