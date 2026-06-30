from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.keyboards.admin.client_management_kb.client_creation_kb import client_creation_kb


async def show_creation_confirmation(message: Message, state: FSMContext):
    data = await state.get_data()

    await message.answer(
        text=(
            "Проверьте данные клиента:\n\n"
            f"ФИО: {data['full_name']}\n"
            f"Телефон: {data['phone']}"
        ),
        reply_markup=client_creation_kb()
    )


async def show_creation_success(state: FSMContext, callback_query: CallbackQuery):

    data = await state.get_data()

    await callback_query.answer('')
    await callback_query.message.edit_text(
        text=f"Клиент:\n\n"
             f"ФИО:  {data['full_name']},\n"
             f"Номер телефона: {data['phone']}\nДобавлен успешно!"
    )