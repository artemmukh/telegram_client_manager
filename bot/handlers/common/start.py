from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.models.user import User  # если есть модель
from bot.utils.info import (
    show_main_admin_menu,
    show_main_client_menu,
)
from bot.utils.role import RoleFilter


def create_start_router():

    router = Router()

    router.message.filter(RoleFilter("*"))

    @router.message(F.text == "/start", RoleFilter("admin"))
    async def start_admin(
        message: Message,
        state: FSMContext,
        current_user: User,
    ):
        await state.clear()
        await show_main_admin_menu(message, current_user.full_name)

    @router.message(F.text == "/start", RoleFilter("client"))
    async def start_client(
        message: Message,
        state: FSMContext,
        current_user: User,
    ):
        await state.clear()
        await show_main_client_menu(message, current_user.full_name)

    return router