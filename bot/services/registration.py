from bot.config.config import admin_ids
from bot.exceptions.user_exceptions import PhoneAlreadyExistsError, UserAlreadyExistsError
from bot.models.user import User
from bot.repositories.user_repository import UserRepository
from bot.validators.validators import validate_full_name, validate_phone


class RegistrationService:
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    async def register(self,
            telegram_user_id: int,
            full_name: str,
            phone: str,

    ) -> User:

        full_name = full_name.strip()
        validate_full_name(full_name)
        validate_phone(phone)

        if await self.user_repository.phone_exists(phone):
            raise PhoneAlreadyExistsError()

        if await self.user_repository.user_exists(telegram_user_id):
            raise UserAlreadyExistsError()

        user = User(
            telegram_user_id=telegram_user_id,
            full_name=full_name,
            phone=phone,
            role=self._detect_role(telegram_user_id),
            is_registered=True,
        )
        await self.user_repository.create_user(user)
        return user

    def _detect_role(self, telegram_user_id: int) -> str:
        return "admin" if telegram_user_id in admin_ids else "client"
