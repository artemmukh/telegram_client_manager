
from bot.exceptions.user_exceptions import PhoneAlreadyExistsError, UserAlreadyExistsError
from bot.models.clinic import Clinic
from bot.models.user import User
from bot.utils.role import Role
from bot.utils.tools import normalize_phone
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.user_repository import UserRepository
from bot.validators.validators import validate_full_name, validate_phone, FULL_NAME_PATTERN


class RegistrationService:
    def __init__(self, user_repository: UserRepository, clinic_repository: ClinicRepository):
        self.user_repository = user_repository
        self.clinic_repository = clinic_repository

    async def get_clinic_by_token(self, token: str) -> Clinic | None:
        return await self.clinic_repository.get_clinic_by_token(token)

    async def register(
            self,
            telegram_user_id: int,
            full_name: str,
            phone: str,
            role: Role,
            clinic_id: int,
    ) -> User:

        full_name = full_name.strip()
        phone = normalize_phone(phone.strip())
        validate_full_name(full_name, FULL_NAME_PATTERN)
        validate_phone(phone)

        if await self.user_repository.user_exists(telegram_user_id):
            raise UserAlreadyExistsError()

        existing = await self.user_repository.get_client_by_phone(phone)

        if existing is not None:
            if existing.telegram_user_id is not None:
                raise PhoneAlreadyExistsError()

            await self.user_repository.update_user_telegram_id(existing.ID, telegram_user_id)
            existing.telegram_user_id = telegram_user_id
            return existing

        user = User(
            full_name=full_name,
            phone=phone,
            clinic_id=clinic_id,
            role=role,
            telegram_user_id=telegram_user_id,
        )

        await self.user_repository.create_user(user)

        return user


