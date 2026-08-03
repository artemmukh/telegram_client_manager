from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from bot.utils.reply_menu_labels import CONTACT_LABEL

_REG_CONFIRM_LABEL = {
    "ru": "✅ Подтверждаю",
    "uz": "✅ Tasdiqlayman",
}

_REG_EDIT_LABEL = {
    "ru": "📝 Изменить",
    "uz": "📝 O'zgartirish",
}

_REG_GUIDE_LABEL = {
    "ru": "❓ Как пройти регистрацию",
    "uz": "❓ Ro'yxatdan qanday o'tish kerak",
}

_REG_NAME_CONFLICT_YES_LABEL = {
    "ru": "✅ Да",
    "uz": "✅ Ha",
}

_REG_NAME_CONFLICT_NO_LABEL = {
    "ru": "❌ Нет",
    "uz": "❌ Yo'q",
}


def contact_keyboard(lang: str = "ru"):
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CONTACT_LABEL.get(lang, CONTACT_LABEL["ru"]), request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def reg_confirm_kb(lang: str = "ru"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_REG_CONFIRM_LABEL.get(lang, _REG_CONFIRM_LABEL["ru"]), callback_data="reg_confirm")],
        [InlineKeyboardButton(text=_REG_EDIT_LABEL.get(lang, _REG_EDIT_LABEL["ru"]), callback_data="reg_edit")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True)


def reg_guide_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_REG_GUIDE_LABEL.get(lang, _REG_GUIDE_LABEL["ru"]), callback_data="reg_guide")]
    ])


def reg_name_conflict_kb(lang: str = "ru"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=_REG_NAME_CONFLICT_YES_LABEL.get(lang, _REG_NAME_CONFLICT_YES_LABEL["ru"]),
            callback_data="reg_name_conflict_yes",
        )],
        [InlineKeyboardButton(
            text=_REG_NAME_CONFLICT_NO_LABEL.get(lang, _REG_NAME_CONFLICT_NO_LABEL["ru"]),
            callback_data="reg_name_conflict_no",
        )]
    ])


_BACK_LABEL = {
    "ru": "⬅️ Назад",
    "uz": "⬅️ Orqaga",
}


def back_to_help_kb(lang: str = "ru"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_BACK_LABEL.get(lang, _BACK_LABEL["ru"]), callback_data="back_to_help")]
    ])


def reg_edit_name_back_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_BACK_LABEL.get(lang, _BACK_LABEL["ru"]),
                    callback_data="reg_edit_name_back"
                )
            ]
        ]
    )

