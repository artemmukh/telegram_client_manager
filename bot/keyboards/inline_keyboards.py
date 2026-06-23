from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def start_keyboard() -> ReplyKeyboardMarkup:
    start_builder = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text="👤 Управление клиентами"),
    KeyboardButton(text="📒 Управление записями")],
    [KeyboardButton(text="❓ Справка"),
    KeyboardButton(text="⚙️ Мой профиль")]],
    resize_keyboard=True, input_field_placeholder='Выберите вариант:')
    return start_builder

def contact_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить контакт", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )



def client_keyboard() -> InlineKeyboardMarkup:
    client_builder = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='1. Добавить клиента', callback_data='create_client'),
         InlineKeyboardButton(text='2. Удалить клиента', callback_data='delete_client')],
        [InlineKeyboardButton(text='3. Поиск клиента', callback_data='search_client'),
         InlineKeyboardButton(text='4. Изменить клиента', callback_data='update_client')
         ]
    ], resize_keyboard=True)
    return client_builder

def record_keyboard() -> InlineKeyboardMarkup:
    record_builder = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='1. Создать запись', callback_data='create_record'),
         InlineKeyboardButton(text='2. Удалить запись', callback_data='delete_record')],
        [InlineKeyboardButton(text='3. Поиск записи', callback_data='search_record'),
         InlineKeyboardButton(text='4. Изменить запись', callback_data='update_record')
         ]
    ], resize_keyboard=True)
    return record_builder