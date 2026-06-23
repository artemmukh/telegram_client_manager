from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


def start_keyboard() -> ReplyKeyboardMarkup:
    start_builder = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="👤 Управление клиентами", callback_data="client_managing"),
    KeyboardButton(text="📒 Управление записями", callback_data="record_managing")],
    [KeyboardButton(text="❓ Справка", callback_data="help"),
    KeyboardButton(text="⚙️ Мой профиль", callback_data="profile")]],
    resize_keyboard=True, input_field_placeholder='Выберите вариант:')
    return start_builder

def client_managing() -> InlineKeyboardMarkup:
    client_builder = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='1. Добавить клиента', callback_data='create_client'),
         InlineKeyboardButton(text='2. Удалить клиента', callback_data='delete_client')],
        [InlineKeyboardButton(text='3. Поиск клиента', callback_data='search_client'),
         InlineKeyboardButton(text='4. Изменить клиента', callback_data='update_client')
         ]
    ], resize_keyboard=True)
    return client_builder

def record_managing() -> InlineKeyboardMarkup:
    record_builder = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='1. Создать запись', callback_data='create_record'),
         InlineKeyboardButton(text='2. Удалить запись', callback_data='delete_record')],
        [InlineKeyboardButton(text='3. Поиск записи', callback_data='search_record'),
         InlineKeyboardButton(text='4. Изменить запись', callback_data='update_record')
         ]
    ], resize_keyboard=True)
    return record_builder