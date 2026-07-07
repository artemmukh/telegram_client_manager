from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import PhoneAlreadyExistsError, UserNotFoundError, ValidationError
from bot.models.clinic import Clinic
from bot.models.user import User
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.staff_repository import StaffRepository
from bot.repositories.user_repository import UserRepository
from bot.services.utils.clinic import resolve_staff_clinic
from bot.utils.role import Role
from bot.utils.tools import normalize_phone
from bot.validators.validators import validate_full_name, validate_phone, FULL_NAME_PATTERN, SEARCH_NAME_PATTERN


class ClientManagement:
    def __init__(
        self,
        user_repository: UserRepository,
        staff_repository: StaffRepository,
        clinic_repository: ClinicRepository,
    ):
        self.user_repository = user_repository
        self.staff_repository = staff_repository
        self.clinic_repository = clinic_repository

    async def create_client(self, admin_telegram_id: int, data: dict) -> User:

        full_name = data['full_name'].strip()
        # Phone is already normalized and validated by the handler layer,
        # but we re-validate to keep the service safe when called from elsewhere.
        phone = data['phone'].strip()

        validate_full_name(full_name, FULL_NAME_PATTERN)
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
        )

        await self.user_repository.create_user(user)

        return user

    async def get_admin_clinic(self, admin_telegram_id: int) -> Clinic:
        return await resolve_staff_clinic(
            self.staff_repository, self.clinic_repository, admin_telegram_id
        )

    async def search_client(self, data) -> User | list[User]:
        phone = data.get("phone")
        full_name = data.get("full_name")

        if phone:
            phone = normalize_phone(phone.strip())

            user = await self.user_repository.get_client_by_phone(phone)

            if user is None:
                raise UserNotFoundError("Клиент не был найден.")

            return [user]

        if full_name:
            full_name = full_name.strip()

            users = await self.user_repository.get_clients_by_name(full_name)

            if not users:
                raise UserNotFoundError("Клиент не был найден.")

            return users

        raise UserNotFoundError("Клиент не был найден.")

    async def delete_client(self, user_id: int) -> bool:

        if user_id:
            await self.user_repository.delete_client(user_id)
            return True

        raise BotException("Ошибка удаления клиента")

    async def update_client_name(self, user_id: int, new_full_name: str) -> User:
        new_full_name = new_full_name.strip()

        validate_full_name(new_full_name, FULL_NAME_PATTERN)

        user = await self.user_repository.get_client_by_id(user_id)

        if user is None:
            raise UserNotFoundError("Клиент не найден.")

        user.full_name = new_full_name

        await self.user_repository.update_client(user_id, user)

        return user

    async def update_client_phone(self, user_id: int, new_phone: str) -> User:
        new_phone = normalize_phone(new_phone.strip())

        validate_phone(new_phone)

        user = await self.user_repository.get_client_by_id(user_id)

        if user is None:
            raise UserNotFoundError("Клиент не найден.")

        if new_phone == user.phone:
            raise ValidationError("Введён такой же номер телефона")

        if await self.user_repository.phone_exists(new_phone):
            raise PhoneAlreadyExistsError("Номер уже зарегистрирован. Пожалуйста, введите другой:")

        user.phone = new_phone

        await self.user_repository.update_client(user_id, user)

        return user
