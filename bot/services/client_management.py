from bot.exceptions.user_exceptions import PhoneAlreadyExistsError, UserAlreadyExistsError
from bot.models.user import User
from bot.repositories.user_repository import UserRepository
from bot.validators.validators import validate_full_name, validate_phone


class ClientManagement:
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    async def create_client(self, data):

        full_name = data['full_name']
        phone = data['phone']
        role = 'client'

        full_name = full_name.strip()
        validate_full_name(full_name)
        validate_phone(phone)

        if await self.user_repository.phone_exists(phone):
            raise PhoneAlreadyExistsError()


        user = User(

            full_name=full_name,
            phone=phone,
            role=role,
            is_registered=True,
        )