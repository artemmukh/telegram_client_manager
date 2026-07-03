from bot.exceptions.user_exceptions import PhoneAlreadyExistsError, UserNotFoundError
from bot.models.user import User
from bot.repositories.user_repository import UserRepository
from bot.utils.role import Role
from bot.utils.tools import normalize_phone
from bot.validators.validators import validate_full_name, validate_phone, FULL_NAME_PATTERN


class ClientManagement:
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    async def create_client(self, data):

        full_name = data['full_name'].strip()
        # Phone is already normalized and validated by the handler layer,
        # but we re-validate to keep the service safe when called from elsewhere.
        phone = data['phone'].strip()

        validate_full_name(full_name, FULL_NAME_PATTERN)
        validate_phone(phone)

        phone = normalize_phone(phone)
        role = Role.CLIENT

        if await self.user_repository.phone_exists(phone):
            raise PhoneAlreadyExistsError()

        user = User(

            full_name=full_name,
            phone=phone,
            role=role
        )

        await self.user_repository.create_user(user)

        return user

    async def search_client(self, data) -> User | list[User]:
        phone = data.get("phone")
        full_name = data.get("full_name")

        if phone:
            phone = normalize_phone(phone.strip())

            user = await self.user_repository.get_user_by_phone(phone)

            if user is None:
                raise UserNotFoundError("Клиент не был найден.")

            return user

        if full_name:
            full_name = full_name.strip()

            users = await self.user_repository.get_users_by_name(full_name)

            if not users:
                raise UserNotFoundError("Клиент не был найден.")

            return users

        raise UserNotFoundError("Клиент не был найден.")