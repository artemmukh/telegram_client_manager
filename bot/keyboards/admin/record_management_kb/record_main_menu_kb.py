from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def record_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="➕ Создать запись",
        callback_data="create_record"
    )

    builder.button(
        text="❌ Удалить запись",
        callback_data="delete_record"
    )

    builder.button(
        text="🔍 Поиск записей",
        callback_data="search_record"
    )

    builder.button(
        text="📝 Изменить запись",
        callback_data="update_record"
    )


    builder.adjust(2, 2, 1)

    return builder.as_markup()