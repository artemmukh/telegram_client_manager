from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.keyboards.client.help_kb import client_help_guide_kb
from bot.keyboards.utils.utils_kb import back_to_help_kb
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
        await message.answer(display_admin_help_msg())

    @router.message(F.text.in_({"/help", "❓ Помощь"}), RoleFilter("client"))
    async def help_client(message: Message):
        await message.answer(display_client_help_msg(), reply_markup=client_help_guide_kb())

    @router.callback_query(F.data == "back_to_help", RoleFilter("client"))
    async def back_to_help_client(callback: CallbackQuery) -> None:
        await callback.message.edit_text(display_client_help_msg(), reply_markup=client_help_guide_kb())

    @router.callback_query(F.data == "client_help_guide", RoleFilter("client"))
    async def help_client_guide(callback: CallbackQuery) -> None:
        await callback.message.edit_text(display_client_help_guide_msg(), reply_markup=back_to_help_kb())


    return router