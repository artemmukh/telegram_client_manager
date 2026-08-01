from aiogram.utils.keyboard import InlineKeyboardBuilder

_BOOK_LABEL = {
    "ru": "✍️ Записаться",
    "uz": "✍️ Yozilish",
}

_HISTORY_LABEL = {
    "ru": "📖 История записей",
    "uz": "📖 Yozuvlar tarixi",
}

_MANAGE_LABEL = {
    "ru": "🔧 Управление записью",
    "uz": "🔧 Yozuvni boshqarish",
}


def client_appointment_management_kb(lang: str = "ru"):
    builder = InlineKeyboardBuilder()

    builder.button(text=_BOOK_LABEL.get(lang, _BOOK_LABEL["ru"]), callback_data="client_book_appointment")
    builder.button(text=_HISTORY_LABEL.get(lang, _HISTORY_LABEL["ru"]), callback_data="client_appointment_history")
    builder.button(text=_MANAGE_LABEL.get(lang, _MANAGE_LABEL["ru"]), callback_data="client_manage_appointment")

    builder.adjust(1, 1, 1)

    return builder.as_markup()
