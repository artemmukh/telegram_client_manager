from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


_REMINDER_SETTINGS_LABEL = {
    "ru": "🔔 Настройки уведомлений",
    "uz": "🔔 Bildirishnoma sozlamalari",
}

_LANGUAGE_LABEL = {
    "ru": "🌐 Язык / Til",
    "uz": "🌐 Язык / Til",
}

_CHANGE_PERSONAL_DATA_LABEL = {
    "ru": "✏️ Изменить личные данные",
    "uz": "✏️ Shaxsiy ma'lumotlarni o'zgartirish",
}

_CHANGE_NAME_LABEL = {
    "ru": "📝 Изменить ФИО",
    "uz": "📝 F.I.Sh.ni o'zgartirish",
}

_ADD_BIRTH_DATE_LABEL = {
    "ru": "🎂 Добавить дату рождения и пол",
    "uz": "🎂 Tug'ilgan sana va jinsni qo'shish",
}

_BACK_LABEL = {
    "ru": "⬅️ Назад",
    "uz": "⬅️ Orqaga",
}

_SPECIFY_BIRTH_DATE_LABEL = {
    "ru": "🎂 Указать дату рождения и пол",
    "uz": "🎂 Tug'ilgan sana va jinsni kiritish",
}


def profile_menu_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=_REMINDER_SETTINGS_LABEL.get(lang, _REMINDER_SETTINGS_LABEL["ru"]),
            callback_data="profile_reminder_settings",
        )],
        [InlineKeyboardButton(
            text=_LANGUAGE_LABEL.get(lang, _LANGUAGE_LABEL["ru"]),
            callback_data="profile_language_settings",
        )],
        [InlineKeyboardButton(
            text=_CHANGE_PERSONAL_DATA_LABEL.get(lang, _CHANGE_PERSONAL_DATA_LABEL["ru"]),
            callback_data="profile_personal_data",
        )],
    ])


def profile_personal_data_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=_CHANGE_NAME_LABEL.get(lang, _CHANGE_NAME_LABEL["ru"]),
            callback_data="profile_change_name",
        )],
        [InlineKeyboardButton(
            text=_ADD_BIRTH_DATE_LABEL.get(lang, _ADD_BIRTH_DATE_LABEL["ru"]),
            callback_data="profile_add_birth_date",
        )],
        [InlineKeyboardButton(text=_BACK_LABEL.get(lang, _BACK_LABEL["ru"]), callback_data="profile_back")],
    ])


def personal_data_broadcast_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=_SPECIFY_BIRTH_DATE_LABEL.get(lang, _SPECIFY_BIRTH_DATE_LABEL["ru"]),
            callback_data="profile_add_birth_date",
        )],
    ])
