from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def profile_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Изменить ФИ", callback_data="profile_change_name")],
        [InlineKeyboardButton(text="🔔 Настройки уведомлений", callback_data="profile_reminder_settings")],
    ])


def personal_data_broadcast_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎂 Указать дату рождения и пол", callback_data="profile_add_birth_date")],
    ])
