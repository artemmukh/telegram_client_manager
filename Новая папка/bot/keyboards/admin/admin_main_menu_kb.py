from aiogram.types import InlineKeyboardMarkup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def start_admin_keyboard() -> ReplyKeyboardMarkup:
    start_builder = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="👤 Управление клиентами"),
    KeyboardButton(text="📒 Управление записями")],
    [KeyboardButton(text="❓ Справка"),
    KeyboardButton(text="⚙️ Мой профиль")]],
    resize_keyboard=True, input_field_placeholder='Выберите вариант:')
    return start_builder