from dataclasses import replace

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.repositories.user_repository import UserRepository
from bot.services.utils.auth import AuthService


class UserContextMiddleware(BaseMiddleware):
    def __init__(self, user_repo: UserRepository, auth_service: AuthService):
        self.user_repo = user_repo
        self.auth_service = auth_service

    async def __call__(self, handler, event: TelegramObject, data: dict):

        from_user = getattr(event, "from_user", None)

        if from_user is not None:
            user = await self.user_repo.get_user_by_telegram_id(from_user.id)
            if user is not None:
                data["current_user"] = replace(
                    user,
                    role=await self.auth_service.resolve_current_role(user),
                )

        return await handler(event, data)
