from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import Message, CallbackQuery
from bot.create_bot import db_path
from bot.exceptions.user_exceptions import InvalidPhoneError, InvalidFullNameError, PhoneAlreadyExistsError
from bot.handlers.utils.admin_utils.confirmations import show_confirmation
from bot.keyboards.utils.utils_kb import cancel_kb
from bot.repositories.user_repository import UserRepository
from bot.validators.validators import validate_phone, validate_full_name, validate_phone_available

user_repo = UserRepository(db_path)


async def ask_full_name(callback: CallbackQuery, state: FSMContext, next_state: State):
    await state.set_state(next_state)
    await callback.answer('')
    await callback.message.edit_text(
        "Введите ФИО:",
        reply_markup=cancel_kb()
    )


async def ask_phone(callback: CallbackQuery, state: FSMContext, next_state: State):
    await state.set_state(next_state)
    await callback.answer('')
    await callback.message.edit_text(
        "Введите номер телефона:",
        reply_markup=cancel_kb()
    )


async def full_name_processing(message: Message, state: FSMContext, next_state: State) -> bool:
    client_full_name = message.text.strip()

    try:
        validate_full_name(client_full_name)
    except InvalidFullNameError as e:
        await message.answer(str(e))
        return False

    await state.update_data(full_name=client_full_name)
    await state.set_state(next_state)
    return True


async def phone_processing(message: Message, state: FSMContext, next_state: State) -> bool:
    try:
        client_phone = validate_phone(message.text.strip())
        await validate_phone_available(user_repo, client_phone)
    except InvalidPhoneError as e:
        await message.answer(str(e))
        return False
    except PhoneAlreadyExistsError as e:
        await message.answer(str(e))
        return False

    await state.update_data(phone=client_phone)
    await state.set_state(next_state)
    return True


async def edit_full_name(callback: CallbackQuery, state: FSMContext, edit_state: State):
    await state.set_state(edit_state)
    await callback.answer('')
    await callback.message.edit_text(
        "Введите новое ФИО:",
        reply_markup=cancel_kb()
    )


async def process_edit_full_name(message: Message, state: FSMContext,
                                 final_state: State, reply_markup=None) -> bool:
    client_full_name = message.text.strip()

    try:
        validate_full_name(client_full_name)
    except InvalidFullNameError as e:
        await message.answer(str(e))
        return False

    await state.update_data(full_name=client_full_name)
    await state.set_state(final_state)
    await show_confirmation(message, state, reply_markup)
    return True


async def edit_phone(callback: CallbackQuery, state: FSMContext, edit_state: State):
    await state.set_state(edit_state)
    await callback.answer('')
    await callback.message.edit_text(
        "Введите новый телефон:",
        reply_markup=cancel_kb()
    )


async def process_edit_phone(message: Message, state: FSMContext,
                             final_state: State, reply_markup=None) -> bool:
    try:
        client_phone = validate_phone(message.text.strip())
        await validate_phone_available(user_repo, client_phone)
    except InvalidPhoneError as e:
        await message.answer(str(e))
        return False
    except PhoneAlreadyExistsError as e:
        await message.answer(str(e))
        return False

    await state.update_data(phone=client_phone)
    await state.set_state(final_state)
    await show_confirmation(message, state, reply_markup)
    return True
