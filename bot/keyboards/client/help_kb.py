from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_HOW_BOT_WORKS_LABEL = {
    "ru": "🧭 Как бот работает",
    "uz": "🧭 Bot qanday ishlaydi",
}


def client_help_guide_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=_HOW_BOT_WORKS_LABEL.get(lang, _HOW_BOT_WORKS_LABEL["ru"]),
            callback_data="client_help_guide",
        )]
    ])
