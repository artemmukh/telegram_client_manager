from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def profile_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔔 Настройки уведомлений", callback_data="profile_reminder_settings")],
        [InlineKeyboardButton(text="✏️ Изменить личные данные", callback_data="profile_personal_data")],
    ])


def profile_personal_data_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Изменить ФИО", callback_data="profile_change_name")],
        [InlineKeyboardButton(text="🎂 Добавить дату рождения и пол", callback_data="profile_add_birth_date")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile_back")],
    ])
