from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.keyboards.admin.record_management_kb.record_main_menu_kb import record_keyboard


def create_admin_record_router():

    router = Router()


    @router.message(F.text.in_({"/record_managing", "📒 Управление записями"}))
    async def record_managing(message: Message):
        await message.answer(text="Выберите действие над записью:", reply_markup=record_keyboard())

    @router.callback_query(F.data == "back_to_main_records")
    async def back_to_main(callback_query: CallbackQuery, state: FSMContext):
        await state.clear()
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Выберите действие над записью:",
            reply_markup=record_keyboard()
        )

    return router