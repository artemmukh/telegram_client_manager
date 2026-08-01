from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

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

CLIENT_MENU_PLACEHOLDER = {
    "ru": "Выберите вариант:",
    "uz": "Variantni tanlang:",
}


def start_client_keyboard(lang: str = "ru") -> ReplyKeyboardMarkup:
    labels = CLIENT_MENU_LABELS.get(lang, CLIENT_MENU_LABELS["ru"])
    placeholder = CLIENT_MENU_PLACEHOLDER.get(lang, CLIENT_MENU_PLACEHOLDER["ru"])

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=labels["records"])],
            [KeyboardButton(text=labels["profile"]),
             KeyboardButton(text=labels["help"])],
             [KeyboardButton(text=labels["price_list"]),
              KeyboardButton(text=labels["location"])],
        ],
        resize_keyboard=True,
        input_field_placeholder=placeholder,
    )
    return keyboard
