from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

_CREATE_RECORD_LABEL = {
    "ru": "➕ Создать запись",
    "uz": "➕ Yozuv yaratish",
}

_RECORDS_LABEL = {
    "ru": "📒 Записи",
    "uz": "📒 Yozuvlar",
}

_SLOT_BLOCKING_LABEL = {
    "ru": "🚫 Блокировка слотов",
    "uz": "🚫 Slotlarni bloklash",
}


def record_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_CREATE_RECORD_LABEL.get(lang, _CREATE_RECORD_LABEL["ru"]),
        callback_data="create_record"
    )

    builder.button(
        text=_RECORDS_LABEL.get(lang, _RECORDS_LABEL["ru"]),
        callback_data="browse_appointments"
    )

    builder.button(
        text=_SLOT_BLOCKING_LABEL.get(lang, _SLOT_BLOCKING_LABEL["ru"]),
        callback_data="slot_blocking_menu"
    )

    builder.adjust(2, 1)

    return builder.as_markup()