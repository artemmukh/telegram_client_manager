from dataclasses import dataclass
from typing import Literal

from bot.exceptions.user_exceptions import ContactOwnershipMismatchError, PhoneAlreadyExistsError, UserAlreadyExistsError, UserNotFoundError
from bot.models.clinic import Clinic
from bot.models.user import User
from bot.utils.role import Role
from bot.utils.tools import normalize_phone
from bot.repositories.client_clinic_repository import ClientClinicRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.user_repository import UserRepository
from bot.services.utils.date_parser import get_current_tashkent_time
from bot.services.utils.personal_data import validate_and_normalize_personal_data
from bot.validators.validators import validate_full_name, validate_phone, SEARCH_NAME_PATTERN


@dataclass
class PhoneLookupResult:
    status: Literal["not_found", "found_unclaimed"]
    existing_user: User | None = None


class RegistrationService:
    def __init__(
            self,
            user_repository: UserRepository,
            clinic_repository: ClinicRepository,
            client_clinic_repository: ClientClinicRepository | None = None,
    ):
        self.user_repository = user_repository
        self.clinic_repository = clinic_repository
        self.client_clinic_repository = client_clinic_repository

    async def get_clinic_by_token(self, token: str) -> Clinic | None:
        return await self.clinic_repository.get_clinic_by_token(token)

    async def check_phone(
        self, phone: str, telegram_user_id: int, contact_user_id: int | None = None,
    ) -> PhoneLookupResult:
        phone = normalize_phone(phone.strip())
        validate_phone(phone)

        if await self.user_repository.user_exists(telegram_user_id):
            raise UserAlreadyExistsError()

        existing = await self.user_repository.get_client_by_phone(phone)

        if existing is None:
            return PhoneLookupResult(status="not_found")

        if existing.telegram_user_id is not None:
            raise PhoneAlreadyExistsError()

        if contact_user_id != telegram_user_id:
            raise ContactOwnershipMismatchError()

        return PhoneLookupResult(status="found_unclaimed", existing_user=existing)

    async def apply_name_conflict_resolution(self, existing_user_id: int, new_full_name: str) -> User:
        new_full_name = new_full_name.strip()
        validate_full_name(new_full_name, SEARCH_NAME_PATTERN)

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
            birth_date: str | None = None,
            gender: str | None = None,
    ) -> User:

        full_name = full_name.strip()
        phone = normalize_phone(phone.strip())
        validate_full_name(full_name, SEARCH_NAME_PATTERN)
        validate_phone(phone)

        birth_date, gender = validate_and_normalize_personal_data(birth_date, gender)

        if existing_user_id is not None:
            user = await self.user_repository.get_client_by_id(existing_user_id)

            if user is None:
                raise UserNotFoundError("Клиент не найден.")

            if user.full_name.strip().casefold() != full_name.casefold():
                user = await self.apply_name_conflict_resolution(existing_user_id, full_name)

            await self.user_repository.update_user_telegram_id(
                existing_user_id, telegram_user_id, gender=gender, birth_date=birth_date,
            )
            user.telegram_user_id = telegram_user_id
            user.gender = gender
            user.birth_date = birth_date
            return user

        if await self.user_repository.user_exists(telegram_user_id):
            raise UserAlreadyExistsError()

        user = User(
            full_name=full_name,
            phone=phone,
            clinic_id=clinic_id,
            role=role,
            telegram_user_id=telegram_user_id,
            created_at=get_current_tashkent_time(),
            gender=gender,
            birth_date=birth_date,
        )

        await self.user_repository.create_user(user)

        if self.client_clinic_repository is not None:
            await self.client_clinic_repository.link_client_to_clinic(user.ID, clinic_id)

        return user
