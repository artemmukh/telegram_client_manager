from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def profile_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Изменить ФИО", callback_data="profile_change_name")],
        [InlineKeyboardButton(text="🔔 Настройки уведомлений", callback_data="profile_reminder_settings")],
    ])
