from aiogram.utils.keyboard import InlineKeyboardBuilder


_TEXTS = {
    "ru": {
        "back_to_menu": "⬅️ К меню",
        "confirm": "✅ Подтвердить",
        "edit_full_name": "📝 Изменить ФИ",
        "edit_phone": "📲 Изменить номер",
        "yes": "✅ Да",
        "no": "❌ Нет",
    },
    "uz": {
        "back_to_menu": "⬅️ Menyuga",
        "confirm": "✅ Tasdiqlash",
        "edit_full_name": "📝 F.I.Sh.ni o'zgartirish",
        "edit_phone": "📲 Raqamni o'zgartirish",
        "yes": "✅ Ha",
        "no": "❌ Yo'q",
    },
}


def _t(lang: str) -> dict:
    return _TEXTS.get(lang, _TEXTS["ru"])


def client_creation_back_kb(lang: str = "ru"):
    """Единственная кнопка "к меню" - для экранов ввода при создании клиента (ФИ/телефон)."""
    builder = InlineKeyboardBuilder()
    builder.button(text=_t(lang)["back_to_menu"], callback_data="back_to_main_menu")
    return builder.as_markup()


def client_creation_kb(lang: str = "ru"):
    texts = _t(lang)
    builder = InlineKeyboardBuilder()

    builder.button(
        text=texts["confirm"], callback_data="client_creation_finish"
    )

    builder.button(text=texts["edit_full_name"], callback_data="client_creation_edit_full_name")

    builder.button(text=texts["edit_phone"], callback_data="client_creation_edit_phone")

    builder.button(text=texts["back_to_menu"], callback_data="back_to_main_menu")

    builder.adjust(1, 2, 1)

    return builder.as_markup()


def client_creation_duplicate_name_kb(lang: str = "ru"):
    texts = _t(lang)
    builder = InlineKeyboardBuilder()

    builder.button(text=texts["yes"], callback_data="client_creation_duplicate_confirm")

    builder.button(text=texts["no"], callback_data="client_creation_duplicate_cancel")

    builder.adjust(2)

    return builder.as_markup()
