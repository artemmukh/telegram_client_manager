from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.repositories.user_repository import UserRepository


class UserContextMiddleware(BaseMiddleware):
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    async def __call__(self, handler, event: TelegramObject, data: dict):

        from_user = getattr(event, "from_user", None)

        if from_user is not None:
            data["current_user"] = await self.user_repo.get_user_by_telegram_id(
                from_user.id
            )

        return await handler(event, data)