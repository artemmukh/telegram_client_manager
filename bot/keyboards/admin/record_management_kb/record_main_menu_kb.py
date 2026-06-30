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


    builder.adjust(2, 2, 1)

    return builder.as_markup()