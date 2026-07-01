from aiogram.utils.keyboard import InlineKeyboardBuilder


def client_creation_kb():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить", callback_data="client_creation_finish"
    )

    builder.button(text="📝 Изменить ФИО", callback_data="client_creation_edit_full_name")

    builder.button(text="📲 Изменить номер", callback_data="client_creation_edit_phone")

    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1, 2, 1)

    return builder.as_markup()