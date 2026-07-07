from aiogram.utils.keyboard import InlineKeyboardBuilder


def client_appointment_management_kb():
    builder = InlineKeyboardBuilder()

    builder.button(text="✍️ Записаться", callback_data="client_book_appointment")
    builder.button(text="📖 История записей", callback_data="client_appointment_history")
    builder.button(text="🔧 Управление записью", callback_data="client_manage_appointment")

    builder.adjust(1, 1, 1)

    return builder.as_markup()
