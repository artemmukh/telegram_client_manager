from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.keyboards.admin.client_management_kb.client_main_menu_kb import client_keyboard
from bot.models.user import User
from bot.utils.role import RoleFilter

_CHOOSE_CLIENT_ACTION = {
    "ru": "Выберите действие над клиентом:",
    "uz": "Mijoz uchun amalni tanlang:",
}


def create_admin_client_menu_router():
    router = Router()

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    @router.message(F.text.in_({
        "/client_managing",
        "👤 Управление клиентами", "👤 Mijozlarni boshqarish",
    }))
    async def client_managing(message: Message, current_user: User):
        lang = current_user.language
        await message.answer(
            text=_CHOOSE_CLIENT_ACTION.get(lang, _CHOOSE_CLIENT_ACTION["ru"]), reply_markup=client_keyboard(lang),
        )

    @router.callback_query(F.data == "back_to_main_menu")
    async def client_managing_callback(callback: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        await state.clear()
        await callback.answer('')
        await callback.message.edit_text(
            text=_CHOOSE_CLIENT_ACTION.get(lang, _CHOOSE_CLIENT_ACTION["ru"]), reply_markup=client_keyboard(lang),
        )

    return router
