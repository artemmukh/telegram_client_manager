from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.utils.gender_cb import GenderCB


_MALE_LABEL = {
    "ru": "Мужской",
    "uz": "Erkak",
}

_FEMALE_LABEL = {
    "ru": "Женский",
    "uz": "Ayol",
}


def gender_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=_MALE_LABEL.get(lang, _MALE_LABEL["ru"]), callback_data=GenderCB(value="male").pack()),
            InlineKeyboardButton(text=_FEMALE_LABEL.get(lang, _FEMALE_LABEL["ru"]), callback_data=GenderCB(value="female").pack()),
        ]
    ])
