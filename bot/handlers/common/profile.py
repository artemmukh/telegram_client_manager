from aiogram import F, Router
from aiogram.types import Message

from bot.create_bot import db_path
from bot.models.user import User
from bot.repositories.user_repository import UserRepository
from bot.utils.role import RoleFilter


def create_profile_router():

    router = Router()

    router.message.filter(RoleFilter("*"))

    @router.message(F.text.in_({"/profile", "⚙️ Мой профиль"}), RoleFilter("*"))
    async def profile(message: Message, current_user: User | None = None):

        if current_user.role == "admin":
            role = "администратор"
        else:
            role = "клиент"

        await message.answer(
            "Профиль\n\n"
            f"ФИО: {current_user.full_name}\n"
            f"ID клиента: {current_user.ID}\n"
            f"Номер телефона: {current_user.phone}\n"
            f"Тип пользователя: {role}"
        )


    return router