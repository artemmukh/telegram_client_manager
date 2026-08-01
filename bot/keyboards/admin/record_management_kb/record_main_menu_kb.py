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

    builder.adjust(2)

    return builder.as_markup()