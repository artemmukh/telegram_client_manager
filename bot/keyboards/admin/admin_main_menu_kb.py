from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from bot.utils.reply_menu_labels import ADMIN_MENU_LABELS

ADMIN_MENU_PLACEHOLDER = {
    "ru": "Выберите вариант:",
    "uz": "Variantni tanlang:",
}


def start_admin_keyboard(lang: str = "ru") -> ReplyKeyboardMarkup:
    labels = ADMIN_MENU_LABELS.get(lang, ADMIN_MENU_LABELS["ru"])
    placeholder = ADMIN_MENU_PLACEHOLDER.get(lang, ADMIN_MENU_PLACEHOLDER["ru"])

    start_builder = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text=labels["clients"]),
    KeyboardButton(text=labels["records"])],
        [KeyboardButton(text=labels["calendar"])],
    [KeyboardButton(text=labels["help"]),
    KeyboardButton(text=labels["profile"])]],
    resize_keyboard=True, input_field_placeholder=placeholder)
    return start_builder