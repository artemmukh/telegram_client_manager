from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def start_admin_keyboard() -> ReplyKeyboardMarkup:
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



from aiogram.utils.keyboard import InlineKeyboardBuilder


def client_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="1. Добавить клиента",
        callback_data="create_client"
    )

    builder.button(
        text="2. Удалить клиента",
        callback_data="delete_client"
    )

    builder.button(
        text="3. Поиск клиента",
        callback_data="search_client"
    )

    builder.button(
        text="4. Изменить клиента",
        callback_data="update_client"
    )

    builder.button(
        text="⬅ Назад",
        callback_data="back_to_main_clients"
    )

    builder.adjust(2, 2, 1)

    return builder.as_markup()



from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def record_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="1. Создать запись",
        callback_data="create_record"
    )

    builder.button(
        text="2. Удалить запись",
        callback_data="delete_record"
    )

    builder.button(
        text="3. Поиск записи",
        callback_data="search_record"
    )

    builder.button(
        text="4. Изменить запись",
        callback_data="update_record"
    )

    builder.button(
        text="⬅ Назад",
        callback_data="back_to_main_records"
    )

    builder.adjust(2, 2, 1)

    return builder.as_markup()