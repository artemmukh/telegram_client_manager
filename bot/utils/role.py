from enum import Enum

from aiogram.filters import BaseFilter
from aiogram.types import Message
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.repositories.user_repository import UserRepository

class Role(Enum):
    ADMIN = "admin"
    CLIENT = "client"


class RoleFilter(BaseFilter):
    """
    Resolves the user's role and passes it to the handler.

    Usage:
        @router.message(F.text == "/start", RoleFilter("admin"))
        async def start_admin(message: Message, role: str): ...

        @router.message(F.text == "/start", RoleFilter("client"))
        async def start_client(message: Message, role: str): ...

        @router.message(F.text == "/start", RoleFilter())  # any registered user
        async def start_any(message: Message, role: str): ...

        @router.message(F.text == "/start", RoleFilter(None))  # unregistered
        async def start_guest(message: Message): ...
    """

    def __init__(self, role: str | None = "*"):
        # "*" -> any registered role; None -> not registered; "admin"/"client" -> exact
        self.role = role

    async def __call__(self, message: Message, user_repo: "UserRepository") -> bool | dict:
        if not await user_repo.user_exists(message.from_user.id):
            return self.role is None  # match only the "guest" branch

        role = await user_repo.get_user_role(message.from_user.id)

        if self.role == "*":
            return {"role": role}
        if role == self.role:
            return {"role": role}
        return False

