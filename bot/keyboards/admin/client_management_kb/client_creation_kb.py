from aiogram.utils.keyboard import InlineKeyboardBuilder


def client_creation_back_kb():
    """Единственная кнопка "к меню" - для экранов ввода при создании клиента (ФИ/телефон)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ К меню", callback_data="back_to_main_menu")
    return builder.as_markup()


def client_creation_kb():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить", callback_data="client_creation_finish"
    )

    builder.button(text="📝 Изменить ФИ", callback_data="client_creation_edit_full_name")

    builder.button(text="📲 Изменить номер", callback_data="client_creation_edit_phone")

    builder.button(text="⬅️ К меню", callback_data="back_to_main_menu")

    builder.adjust(1, 2, 1)

    return builder.as_markup()


def client_creation_duplicate_name_kb():

    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Да", callback_data="client_creation_duplicate_confirm")

    builder.button(text="❌ Нет", callback_data="client_creation_duplicate_cancel")

    builder.adjust(2)

    return builder.as_markup()