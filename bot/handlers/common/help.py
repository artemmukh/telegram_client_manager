from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

import bot.messages.common as msg
from bot.keyboards.client.help_kb import client_help_guide_kb
from bot.keyboards.utils.utils_kb import back_to_help_kb
from bot.utils.role import RoleFilter

def create_help_router():

    router = Router()

    router.message.filter(RoleFilter("*"))

    @router.message(F.text.in_({"/help", "❓ Справка", "❓ Ma'lumot"}), RoleFilter("admin"))
    async def help_admin(message: Message):
        await message.answer(msg.ADMIN_HELP)

    @router.message(F.text.in_({"/help", "❓ Помощь", "❓ Yordam"}), RoleFilter("client"))
    async def help_client(message: Message):
        await message.answer(msg.CLIENT_HELP, reply_markup=client_help_guide_kb())

    @router.callback_query(F.data == "back_to_help", RoleFilter("client"))
    async def back_to_help_client(callback: CallbackQuery) -> None:
        await callback.message.edit_text(msg.CLIENT_HELP, reply_markup=client_help_guide_kb())
        await callback.answer()

    @router.callback_query(F.data == "client_help_guide", RoleFilter("client"))
    async def help_client_guide(callback: CallbackQuery) -> None:
        await callback.message.edit_text(msg.CLIENT_HELP_GUIDE, reply_markup=back_to_help_kb())
        await callback.answer()


    return router