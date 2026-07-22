from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def contact_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить контакт", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def reg_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтверждаю", callback_data="reg_confirm")],
        [InlineKeyboardButton(text="📝 Изменить", callback_data="reg_edit")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True)


def reg_guide_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❓ Как пройти регистрацию", callback_data="reg_guide")]
    ])


def reg_name_conflict_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="reg_name_conflict_yes")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="reg_name_conflict_no")]
    ])


def back_to_help_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_help")]
    ])


def reg_edit_name_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data="reg_edit_name_back"
                )
            ]
        ]
    )

