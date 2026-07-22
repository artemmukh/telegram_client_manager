from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.utils.gender_cb import GenderCB


def gender_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Мужской", callback_data=GenderCB(value="male").pack()),
            InlineKeyboardButton(text="Женский", callback_data=GenderCB(value="female").pack()),
        ]
    ])
