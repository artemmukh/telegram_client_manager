from aiogram.utils.keyboard import InlineKeyboardBuilder


_TEXTS = {
    "ru": {
        "add_client": "➕ Добавить клиента",
        "clients": "👥 Клиенты",
        "back_to_menu": "⬅️ К меню",
    },
    "uz": {
        "add_client": "➕ Mijoz qo'shish",
        "clients": "👥 Mijozlar",
        "back_to_menu": "⬅️ Menyuga",
    },
}


def _t(lang: str) -> dict:
    return _TEXTS.get(lang, _TEXTS["ru"])


def client_keyboard(lang: str = "ru"):
    texts = _t(lang)
    builder = InlineKeyboardBuilder()

    builder.button(
        text=texts["add_client"],
        callback_data="create_client"
    )

    builder.button(
        text=texts["clients"],
        callback_data="browse_clients"
    )

    builder.adjust(2)

    return builder.as_markup()


def back_to_menu_kb(lang: str = "ru"):
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_t(lang)["back_to_menu"],
        callback_data="back_to_main_menu"
    )

    return builder.as_markup()
