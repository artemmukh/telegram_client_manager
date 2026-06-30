from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def start_client_keyboard() -> ReplyKeyboardMarkup:
    start_builder = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="📝 Записаться"),
    KeyboardButton(text="📒 История записей")],
    [KeyboardButton(text="❓ Справка"),
    KeyboardButton(text="⚙️ Мой профиль")]],
    resize_keyboard=True, input_field_placeholder='Выберите вариант:')
    return start_builder