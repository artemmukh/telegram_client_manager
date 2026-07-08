from collections.abc import Callable, Awaitable

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import Message, CallbackQuery

from bot.exceptions.user_exceptions import InvalidFullNameError, ValidationError
from bot.validators.validators import validate_phone, validate_full_name


async def ask_full_name(callback: CallbackQuery, state: FSMContext, next_state: State, reply_markup):
    await state.set_state(next_state)
    await callback.answer('')
    await callback.message.edit_text(
        "Введите ФИО:",
        reply_markup=reply_markup
    )


async def ask_phone(callback: CallbackQuery, state: FSMContext, next_state: State, reply_markup):
    await state.set_state(next_state)
    await callback.answer('')
    await callback.message.edit_text(
        "Введите номер телефона:",
        reply_markup=reply_markup
    )


async def full_name_processing(message: Message, state: FSMContext, next_state: State, re_pattern) -> bool:
    client_full_name = message.text.strip()

    try:
        validate_full_name(client_full_name, re_pattern)
    except InvalidFullNameError as e:
        await message.answer(str(e))
        return False

    await state.update_data(full_name=client_full_name)
    await state.set_state(next_state)
    return True


async def phone_processing(message: Message,
    state: FSMContext,
    *,
    final_state: State,
    validator: Callable[[str], Awaitable[None]] | None = None,
) -> bool:

    try:
        client_phone = validate_phone(message.text.strip())

        if validator is not None:
            await validator(client_phone)

    except ValidationError as e:
        await message.answer(str(e))
        return False

    await state.update_data(phone=client_phone)
    await state.set_state(final_state)
    return True


async def edit_full_name(callback: CallbackQuery, state: FSMContext, edit_state: State, reply_markup):
    await state.set_state(edit_state)
    await callback.answer('')
    await callback.message.edit_text(
        "Введите новое ФИО:",
        reply_markup=reply_markup
    )


async def edit_phone(callback: CallbackQuery, state: FSMContext, edit_state: State, reply_markup):
    await state.set_state(edit_state)
    await callback.answer('')
    await callback.message.edit_text(
        "Введите новый номер телефона:",
        reply_markup=reply_markup
    )
