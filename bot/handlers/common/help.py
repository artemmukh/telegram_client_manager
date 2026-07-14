from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.utils.info import (
    display_admin_help_msg,
    display_client_help_guide_msg,
    display_client_help_msg,
)
from bot.utils.role import RoleFilter

def create_help_router():

    router = Router()

    router.message.filter(RoleFilter("*"))

    @router.message(F.text.in_({"/help", "❓ Справка"}), RoleFilter("admin"))
    async def help_admin(message: Message):
        await display_admin_help_msg(message)

    @router.message(F.text.in_({"/help", "❓ Помощь"}), RoleFilter("client"))
    async def help_client(message: Message):
        await display_client_help_msg(message)

    @router.callback_query(F.data == "client_help_guide", RoleFilter("client"))
    async def help_client_guide(callback: CallbackQuery) -> None:
        await display_client_help_guide_msg(callback.message)
        await callback.answer()

    return router