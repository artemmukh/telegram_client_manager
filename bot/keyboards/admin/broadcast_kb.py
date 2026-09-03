from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def broadcast_preview_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить текст", callback_data="broadcast_edit_text")],
        [InlineKeyboardButton(text="📤 Разослать сообщение", callback_data="broadcast_send")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile_reminder_settings")],
    ])


def broadcast_confirmation_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, разослать", callback_data="broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")],
    ])
