from aiogram.utils.keyboard import InlineKeyboardBuilder


def client_keyboard():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="➕ Добавить клиента",
        callback_data="create_client"
    )

    builder.button(
        text="❌ Удалить клиента",
        callback_data="delete_client"
    )

    builder.button(
        text="🔍 Поиск клиента",
        callback_data="search_client"
    )

    builder.button(
        text="📝 Изменить клиента",
        callback_data="update_client"
    )

    builder.adjust(2, 2)

    return builder.as_markup()


def back_to_menu_kb():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬅️ К меню",
        callback_data="back_to_main_menu"
    )

    return builder.as_markup()