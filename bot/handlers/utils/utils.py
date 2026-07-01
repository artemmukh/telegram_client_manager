from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery



async def show_confirmation(message: Message, state: FSMContext, reply_markup=None):
    data = await state.get_data()


    await message.answer(
        text=(
            "Проверьте данные:\n\n"
            f"ФИО: {data['full_name']}\n"
            f"Телефон: {data['phone']}"
        ),
        reply_markup=reply_markup
    )


async def show_creation_success(state: FSMContext, callback_query: CallbackQuery):

    data = await state.get_data()

    await callback_query.answer('')
    await callback_query.message.edit_text(
        text=f"Клиент:\n\n"
             f"ФИО:  {data['full_name']},\n"
             f"Номер телефона: {data['phone']}\nДобавлен успешно!"
    )