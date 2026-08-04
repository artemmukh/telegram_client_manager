from collections.abc import Callable, Awaitable

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import Message, CallbackQuery

from bot.exceptions.user_exceptions import InvalidBirthDateError, InvalidFullNameError, ValidationError
from bot.validators.validators import validate_phone, validate_full_name, validate_birth_date


ASK_FULL_NAME_PROMPT = {
    "ru": "Введите ФИ:",
    "uz": "F.I.Sh.ni kiriting:",
}

ASK_PHONE_PROMPT = {
    "ru": "Введите номер телефона:",
    "uz": "Telefon raqamini kiriting:",
}


async def ask_full_name(
    event: CallbackQuery | Message, state: FSMContext, next_state: State, reply_markup, lang: str = "ru",
):
    await state.set_state(next_state)
    text = ASK_FULL_NAME_PROMPT.get(lang, ASK_FULL_NAME_PROMPT["ru"])

    if isinstance(event, CallbackQuery):
        await event.answer('')
        await event.message.edit_text(text, reply_markup=reply_markup)
    else:
        await event.answer(text, reply_markup=reply_markup)


async def ask_phone(callback: CallbackQuery, state: FSMContext, next_state: State, reply_markup, lang: str = "ru"):
    await state.set_state(next_state)
    await callback.answer('')
    await callback.message.edit_text(
        ASK_PHONE_PROMPT.get(lang, ASK_PHONE_PROMPT["ru"]),
        reply_markup=reply_markup
    )


async def full_name_processing(
    message: Message, state: FSMContext, next_state: State, re_pattern, lang: str = "ru",
) -> bool:
    client_full_name = message.text.strip()

    try:
        validate_full_name(client_full_name, re_pattern)
    except InvalidFullNameError as e:
        await message.answer(e.localized(lang))
        return False

    await state.update_data(full_name=client_full_name)
    await state.set_state(next_state)
    return True


async def birth_date_processing(message: Message, state: FSMContext, next_state: State, lang: str = "ru") -> bool:
    birth_date = message.text.strip()

    try:
        validate_birth_date(birth_date)
    except InvalidBirthDateError as e:
        await message.answer(e.localized(lang))
        return False

    await state.update_data(birth_date=birth_date)
    await state.set_state(next_state)
    return True


async def phone_processing(message: Message,
    state: FSMContext,
    *,
    final_state: State,
    validator: Callable[[str], Awaitable[None]] | None = None,
    lang: str = "ru",
) -> bool:

    try:
        client_phone = validate_phone(message.text.strip())

        if validator is not None:
            await validator(client_phone)

    except ValidationError as e:
        await message.answer(e.localized(lang))
        return False

    await state.update_data(phone=client_phone)
    await state.set_state(final_state)
    return True


EDIT_FULL_NAME_PROMPT = {
    "ru": "Введите новое ФИ:",
    "uz": "Yangi F.I.Sh.ni kiriting:",
}


async def edit_full_name(
    callback: CallbackQuery, state: FSMContext, edit_state: State, reply_markup, lang: str = "ru",
):
    await state.set_state(edit_state)
    await callback.answer('')
    await callback.message.edit_text(
        EDIT_FULL_NAME_PROMPT.get(lang, EDIT_FULL_NAME_PROMPT["ru"]),
        reply_markup=reply_markup
    )


EDIT_PHONE_PROMPT = {
    "ru": "Введите новый номер телефона:",
    "uz": "Yangi telefon raqamini kiriting:",
}


async def edit_phone(callback: CallbackQuery, state: FSMContext, edit_state: State, reply_markup, lang: str = "ru"):
    await state.set_state(edit_state)
    await callback.answer('')
    await callback.message.edit_text(
        EDIT_PHONE_PROMPT.get(lang, EDIT_PHONE_PROMPT["ru"]),
        reply_markup=reply_markup
    )
