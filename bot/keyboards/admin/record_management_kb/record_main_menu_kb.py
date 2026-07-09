from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def record_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="➕ Создать запись",
        callback_data="create_record"
    )

    builder.button(
        text="📒 Записи",
        callback_data="browse_appointments"
    )

    builder.adjust(2)

    return builder.as_markup()