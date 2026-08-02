from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

import bot.messages.common as msg
from bot.keyboards.client.help_kb import client_help_guide_kb
from bot.keyboards.utils.utils_kb import back_to_help_kb
from bot.models.user import User
from bot.utils.role import RoleFilter

def create_help_router():

    router = Router()

    router.message.filter(RoleFilter("*"))

    @router.message(F.text.in_({"/help", "❓ Справка", "❓ Ma'lumot"}), RoleFilter("admin"))
    async def help_admin(message: Message, current_user: User):
        await message.answer(msg.admin_help(current_user.language))

    @router.message(F.text.in_({"/help", "❓ Помощь", "❓ Yordam"}), RoleFilter("client"))
    async def help_client(message: Message, current_user: User):
        await message.answer(
            msg.client_help(current_user.language),
            reply_markup=client_help_guide_kb(current_user.language),
        )

    @router.callback_query(F.data == "back_to_help", RoleFilter("client"))
    async def back_to_help_client(callback: CallbackQuery, current_user: User) -> None:
        await callback.message.edit_text(
            msg.client_help(current_user.language),
            reply_markup=client_help_guide_kb(current_user.language),
        )
        await callback.answer()

    @router.callback_query(F.data == "client_help_guide", RoleFilter("client"))
    async def help_client_guide(callback: CallbackQuery, current_user: User) -> None:
        await callback.message.edit_text(
            msg.client_help_guide(current_user.language),
            reply_markup=back_to_help_kb(current_user.language),
        )
        await callback.answer()


    return router