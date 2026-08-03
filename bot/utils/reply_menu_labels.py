CLIENT_MENU_LABELS = {
    "ru": {
        "records": "📋 Управление записями",
        "profile": "👤 Профиль",
        "help": "❓ Помощь",
        "price_list": "📋 Прайс-лист",
        "location": "📍 Локация",
    },
    "uz": {
        "records": "📋 Yozuvlarni boshqarish",
        "profile": "👤 Profil",
        "help": "❓ Yordam",
        "price_list": "📋 Narxlar ro'yxati",
        "location": "📍 Manzil",
    },
}

ADMIN_MENU_LABELS = {
    "ru": {
        "clients": "👤 Управление клиентами",
        "records": "📒 Управление записями",
        "calendar": "📆 Календарь",
        "help": "❓ Справка",
        "profile": "⚙️ Мой профиль",
    },
    "uz": {
        "clients": "👤 Mijozlarni boshqarish",
        "records": "📒 Yozuvlarni boshqarish",
        "calendar": "📆 Kalendar",
        "help": "❓ Ma'lumot",
        "profile": "⚙️ Mening profilim",
    },
}

CONTACT_LABEL = {
    "ru": "📱 Отправить контакт",
    "uz": "📱 Kontaktni yuborish",
}

ALL_REPLY_MENU_LABELS: set[str] = {
    label
    for menu in (CLIENT_MENU_LABELS, ADMIN_MENU_LABELS)
    for lang_labels in menu.values()
    for label in lang_labels.values()
} | set(CONTACT_LABEL.values())


def is_reply_menu_label(text: str) -> bool:
    """True if `text` is an EXACT match (after stripping) for a known
    persistent reply-keyboard button label, in either language. Used to
    detect a user tapping a menu button instead of typing free text into
    an in-progress FSM field.
    """
    return text.strip() in ALL_REPLY_MENU_LABELS


REPLY_MENU_TEXT_MESSAGE = {
    "ru": "Похоже, вы нажали кнопку меню, а не ввели текст. Сначала завершите текущий шаг или нажмите «Отмена»/«Назад».",
    "uz": "Siz matn kiritish o'rniga menyu tugmasini bosganga o'xshaysiz. Avval joriy qadamni yakunlang yoki «Bekor qilish»/«Orqaga» tugmasini bosing.",
}
