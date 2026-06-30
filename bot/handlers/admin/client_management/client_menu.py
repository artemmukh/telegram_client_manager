from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from bot.keyboards.admin.client_management_kb.client_main_menu_kb import client_keyboard


def create_admin_client_menu_router():

    router = Router()

    @router.message(F.text.in_({"/client_managing", "👤 Управление клиентами"}))
    async def client_managing(message: Message):
        await message.answer(text="Выберите действие над клиентом:", reply_markup=client_keyboard())



    @router.callback_query(F.data == "back_to_main_clients")
    async def back_to_main(callback_query: CallbackQuery):
        await callback_query.message.edit_text(text="Выберите действие над клиентом:", reply_markup=client_keyboard())


    return router