from dataclasses import dataclass
from typing import Literal

from bot.exceptions.user_exceptions import PhoneAlreadyExistsError, UserAlreadyExistsError, UserNotFoundError
from bot.models.clinic import Clinic
from bot.models.user import User
from bot.utils.role import Role
from bot.utils.tools import normalize_phone
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.user_repository import UserRepository
from bot.validators.validators import validate_full_name, validate_phone, FULL_NAME_PATTERN


@dataclass
class PhoneLookupResult:
    status: Literal["not_found", "found_unclaimed"]
    existing_user: User | None = None


class RegistrationService:
    def __init__(self, user_repository: UserRepository, clinic_repository: ClinicRepository):
        self.user_repository = user_repository
        self.clinic_repository = clinic_repository

    async def get_clinic_by_token(self, token: str) -> Clinic | None:
        return await self.clinic_repository.get_clinic_by_token(token)

    async def check_phone(self, phone: str, telegram_user_id: int) -> PhoneLookupResult:
        phone = normalize_phone(phone.strip())
        validate_phone(phone)

        if await self.user_repository.user_exists(telegram_user_id):
            raise UserAlreadyExistsError()

        existing = await self.user_repository.get_client_by_phone(phone)

        if existing is None:
            return PhoneLookupResult(status="not_found")

        if existing.telegram_user_id is not None:
            raise PhoneAlreadyExistsError()

        return PhoneLookupResult(status="found_unclaimed", existing_user=existing)

    async def apply_name_conflict_resolution(self, existing_user_id: int, new_full_name: str) -> User:
        new_full_name = new_full_name.strip()
        validate_full_name(new_full_name, FULL_NAME_PATTERN)

        user = await self.user_repository.get_client_by_id(existing_user_id)

        if user is None:
            raise UserNotFoundError("Клиент не найден.")

        user.full_name = new_full_name
        await self.user_repository.update_client(existing_user_id, user)

        return user

    async def register(
            self,
            telegram_user_id: int,
            full_name: str,
            phone: str,
            role: Role,
            clinic_id: int,
            existing_user_id: int | None = None,
    ) -> User:

        full_name = full_name.strip()
        phone = normalize_phone(phone.strip())
        validate_full_name(full_name, FULL_NAME_PATTERN)
        validate_phone(phone)

        if existing_user_id is not None:
            user = await self.user_repository.get_client_by_id(existing_user_id)

            if user is None:
                raise UserNotFoundError("Клиент не найден.")

            if user.full_name.strip().casefold() != full_name.casefold():
                user = await self.apply_name_conflict_resolution(existing_user_id, full_name)

            await self.user_repository.update_user_telegram_id(existing_user_id, telegram_user_id)
            user.telegram_user_id = telegram_user_id
            return user

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
