from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from bot.keyboards.admin.client_management_kb.client_main_menu_kb import client_keyboard
from bot.keyboards.admin.record_management_kb.record_main_menu_kb import record_keyboard
from bot.keyboards.admin.admin_main_menu_kb import start_admin_keyboard


def create_admin_record_router(record_repo):

    router = Router()


    @router.message(F.text.in_({"/record_managing", "📒 Управление записями"}))
    async def record_managing(message: Message):
        await message.answer(text="Выберите действие над записью:", reply_markup=record_keyboard())

    @router.callback_query(F.data.in_({"back_to_main_clients", "back_to_main_records"}))
    async def back_to_main(callback_query: CallbackQuery):

        match callback_query.data:
            case "back_to_main_clients":
                await callback_query.message.edit_text(
                    "Выберите действие над клиентом:",
                    reply_markup=client_keyboard()
                )

            case "back_to_main_records":
                await callback_query.message.edit_text(
                    "Выберите действие над записью:",
                    reply_markup=record_keyboard()
                )
    return router