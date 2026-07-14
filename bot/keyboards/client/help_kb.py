from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def client_help_guide_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧭 Как бот работает", callback_data="client_help_guide")]
    ])
