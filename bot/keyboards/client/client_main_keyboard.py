from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def start_client_keyboard() -> ReplyKeyboardMarkup:
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Управление записями")],
            [KeyboardButton(text="👤 Профиль"),
             KeyboardButton(text="❓ Помощь")],
             [KeyboardButton(text="📋 Прайс-лист"),
              KeyboardButton(text="📍 Локация")],
        ],
        resize_keyboard=True,
        input_field_placeholder='Выберите вариант:'
    )
    return keyboard
