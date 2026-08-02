from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import (
    PHONE_ALREADY_EXISTS_MESSAGE,
    PhoneAlreadyExistsError,
    UserNotFoundError,
    ValidationError,
)
from bot.models.clinic import Clinic
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.client_clinic_repository import ClientClinicRepository
from bot.repositories.staff_repository import StaffRepository
from bot.repositories.user_repository import UserRepository
from bot.repositories.user_settings_repository import UserSettingsRepository
from bot.services.utils.clinic import resolve_staff_clinic
from bot.services.utils.date_parser import get_current_tashkent_time
from bot.services.utils.personal_data import validate_and_normalize_personal_data
from bot.utils.role import Role
from bot.utils.tools import normalize_phone
from bot.validators.validators import validate_full_name, validate_phone, FULL_NAME_PATTERN, SEARCH_NAME_PATTERN

_CLIENT_NOT_FOUND_MESSAGE = {
    "ru": "Клиент не найден.",
    "uz": "Mijoz topilmadi.",
}

_CLIENT_NOT_FOUND_SEARCH_MESSAGE = {
    "ru": "Клиент не был найден.",
    "uz": "Mijoz topilmadi.",
}

_SAME_PHONE_MESSAGE = {
    "ru": "Введён такой же номер телефона",
    "uz": "Xuddi shu telefon raqami kiritildi",
}

_USER_NOT_FOUND_MESSAGE = {
    "ru": "Пользователь не найден.",
    "uz": "Foydalanuvchi topilmadi.",
}

_CLIENT_DELETE_ERROR_MESSAGE = {
    "ru": "Ошибка удаления клиента",
    "uz": "Mijozni o'chirishda xatolik",
}

_APPOINTMENT_COUNT_UNAVAILABLE_MESSAGE = {
    "ru": "Проверка количества записей недоступна",
    "uz": "Yozuvlar sonini tekshirish mavjud emas",
}


class ClientManagement:
    def __init__(
        self,
        user_repository: UserRepository,
        staff_repository: StaffRepository,
        clinic_repository: ClinicRepository,
        appointment_repository: AppointmentRepository | None = None,
        client_clinic_repository: ClientClinicRepository | None = None,
        user_settings_repository: UserSettingsRepository | None = None,
    ):
        self.user_repository = user_repository
        self.staff_repository = staff_repository
        self.clinic_repository = clinic_repository
        self.appointment_repository = appointment_repository
        self.client_clinic_repository = client_clinic_repository
        self.user_settings_repository = user_settings_repository

    async def create_client(self, admin_telegram_id: int, data: dict) -> User:

        full_name = data['full_name'].strip()
        # Phone is already normalized and validated by the handler layer,
        # but we re-validate to keep the service safe when called from elsewhere.
        phone = data['phone'].strip()

        validate_full_name(full_name, SEARCH_NAME_PATTERN)
        validate_phone(phone)

        phone = normalize_phone(phone)

        clinic = await self.get_admin_clinic(admin_telegram_id)

        if await self.user_repository.phone_exists(phone):
            raise PhoneAlreadyExistsError()

        user = User(
            full_name=full_name,
            phone=phone,
            role=Role.CLIENT,
            clinic_id=clinic.clinic_id,
            clinic_name=clinic.name,
            created_at=get_current_tashkent_time(),
        )

        await self.user_repository.create_user(user)

        if self.client_clinic_repository is not None:
            await self.client_clinic_repository.link_client_to_clinic(user.ID, clinic.clinic_id)

        return user

    async def get_admin_clinic(self, admin_telegram_id: int) -> Clinic:
        return await resolve_staff_clinic(
            self.staff_repository, self.clinic_repository, admin_telegram_id
        )

    async def get_client_by_id(self, user_id: int, clinic_id: int) -> User | None:
        client = await self.user_repository.get_client_by_id(user_id)
        if client is None or self.client_clinic_repository is None:
            return None
        if not await self.client_clinic_repository.client_linked_to_clinic(user_id, clinic_id):
            return None
        return client

    async def _ensure_client_in_clinic(self, user_id: int, clinic_id: int) -> User:
        client = await self.user_repository.get_client_by_id(user_id)
        if client is None or self.client_clinic_repository is None:
            raise UserNotFoundError(_CLIENT_NOT_FOUND_MESSAGE)
        if not await self.client_clinic_repository.client_linked_to_clinic(user_id, clinic_id):
            raise UserNotFoundError(_CLIENT_NOT_FOUND_MESSAGE)
        return client

    async def is_phone_taken(self, phone: str) -> bool:
        return await self.user_repository.phone_exists(phone)

    async def search_client(self, data: dict, clinic_id: int) -> User | list[User]:
        phone = data.get("phone")
        full_name = data.get("full_name")

        if phone:
            phone = normalize_phone(phone.strip())

            user = await self.user_repository.get_client_by_phone_in_clinic(phone, clinic_id)

            if user is None:
                raise UserNotFoundError(_CLIENT_NOT_FOUND_SEARCH_MESSAGE)

            return [user]

        if full_name:
            full_name = full_name.strip()

            users = await self.user_repository.get_clients_by_name_in_clinic(full_name, clinic_id)

            if not users:
                raise UserNotFoundError(_CLIENT_NOT_FOUND_SEARCH_MESSAGE)

            return users

        raise UserNotFoundError(_CLIENT_NOT_FOUND_SEARCH_MESSAGE)

    async def find_clients_by_exact_name(self, full_name: str, clinic_id: int) -> list[User]:
        full_name = full_name.strip()
        return await self.user_repository.get_clients_by_exact_name(full_name, clinic_id)

    async def delete_client(self, user_id: int, clinic_id: int) -> bool:
        """Returns True if the client was fully deleted, False if only unlinked from this clinic."""

        if not user_id:
            raise BotException(_CLIENT_DELETE_ERROR_MESSAGE)

        await self._ensure_client_in_clinic(user_id, clinic_id)

        await self.client_clinic_repository.unlink_client_from_clinic(user_id, clinic_id)

        remaining_clinic_ids = await self.client_clinic_repository.get_client_clinic_ids(user_id)
        if remaining_clinic_ids:
            return False

        await self.user_repository.delete_client(user_id)
        return True

    async def count_client_appointments(self, user_id: int, clinic_id: int) -> int:
        if self.appointment_repository is None:
            raise BotException(_APPOINTMENT_COUNT_UNAVAILABLE_MESSAGE)
        return await self.appointment_repository.count_appointments_by_client_id(user_id, clinic_id)

    async def is_last_linked_clinic(self, user_id: int, clinic_id: int) -> bool:
        if self.client_clinic_repository is None:
            raise UserNotFoundError(_CLIENT_NOT_FOUND_MESSAGE)
        clinic_ids = await self.client_clinic_repository.get_client_clinic_ids(user_id)
        return clinic_id in clinic_ids and len(clinic_ids) <= 1

    async def update_client_name(self, user_id: int, new_full_name: str, clinic_id: int) -> User:
        new_full_name = new_full_name.strip()

        validate_full_name(new_full_name, FULL_NAME_PATTERN)

        user = await self._ensure_client_in_clinic(user_id, clinic_id)

        user.full_name = new_full_name

        await self.user_repository.update_client(user_id, user)

        return user

    async def update_client_phone(self, user_id: int, new_phone: str, clinic_id: int) -> User:
        new_phone = normalize_phone(new_phone.strip())

        validate_phone(new_phone)

        user = await self._ensure_client_in_clinic(user_id, clinic_id)

        if new_phone == user.phone:
            raise ValidationError(_SAME_PHONE_MESSAGE)

        if await self.user_repository.phone_exists(new_phone):
            raise PhoneAlreadyExistsError(PHONE_ALREADY_EXISTS_MESSAGE)

        user.phone = new_phone

        await self.user_repository.update_client(user_id, user)

        return user

    async def request_name_change(self, user_id: int, new_full_name: str) -> User:
        new_full_name = new_full_name.strip()

        validate_full_name(new_full_name, FULL_NAME_PATTERN)

        await self.user_repository.set_pending_full_name(user_id, new_full_name)

        user = await self.user_repository.get_user_by_id(user_id)

        if user is None:
            raise UserNotFoundError(_USER_NOT_FOUND_MESSAGE)

        return user

    async def approve_name_change(self, user_id: int, clinic_id: int) -> User | None:
        await self._ensure_client_in_clinic(user_id, clinic_id)
        return await self.user_repository.resolve_pending_full_name(user_id, approve=True)

    async def reject_name_change(self, user_id: int, clinic_id: int) -> User | None:
        await self._ensure_client_in_clinic(user_id, clinic_id)
        return await self.user_repository.resolve_pending_full_name(user_id, approve=False)

    async def update_reminder_preferences(self, user_id: int, preset: str) -> User:
        presets = {
            "both": (True, True),
            "24_only": (True, False),
            "2_only": (False, True),
            "off": (False, False),
        }
        if preset not in presets:
            raise ValidationError(f"Неизвестный вариант настроек напоминаний: {preset}")
        reminder_24h, reminder_2h = presets[preset]

        user = await self.user_repository.get_user_by_id(user_id)
        if user is None:
            raise UserNotFoundError(_USER_NOT_FOUND_MESSAGE)

        await self.user_settings_repository.upsert(user_id, reminder_24h, reminder_2h)
        user.reminder_24h = reminder_24h
        user.reminder_2h = reminder_2h
        return user

    async def update_language(self, user_id: int, language: str) -> User:
        if language not in ("ru", "uz"):
            raise ValidationError(f"Неизвестный язык: {language}")

        user = await self.user_repository.get_user_by_id(user_id)
        if user is None:
            raise UserNotFoundError(_USER_NOT_FOUND_MESSAGE)

        await self.user_settings_repository.set_language(user_id, language)
        user.language = language
        return user

    async def update_personal_data(self, user_id: int, *, birth_date: str | None, gender: str | None) -> User:
        birth_date, gender = validate_and_normalize_personal_data(birth_date, gender)

        user = await self.user_repository.get_user_by_id(user_id)
        if user is None:
            raise UserNotFoundError(_USER_NOT_FOUND_MESSAGE)

        await self.user_repository.update_personal_data(user_id, gender=gender, birth_date=birth_date)
        user.gender = gender
        user.birth_date = birth_date
        return user
