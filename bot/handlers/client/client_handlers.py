from aiogram import Router
from bot.keyboards.admin.client_management_kb.client_main_menu_kb import client_keyboard
from bot.keyboards.admin.record_management_kb.record_main_menu_kb import record_keyboard
from bot.utils.role import RoleFilter


def create_client_router(user_repo, record_repo):


    router = Router()

    router.message.filter(RoleFilter("client"))
    router.callback_query.filter(RoleFilter("client"))

    return router
