from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.utils.language_cb import LanguageCB

LANGUAGE_LABELS = {
    "ru": "🇷🇺 Русский",
    "uz": "🇺🇿 O'zbekcha",
}


def language_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=label,
                callback_data=LanguageCB(value=code).pack(),
            )
            for code, label in LANGUAGE_LABELS.items()
        ]
    ])


def language_settings_kb(current_language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"✅ {label}" if code == current_language else label,
                callback_data=LanguageCB(value=code).pack(),
            )
            for code, label in LANGUAGE_LABELS.items()
        ]
    ])
