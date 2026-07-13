from aiogram.utils.keyboard import InlineKeyboardBuilder


def client_creation_confirm_kb():
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Подтвердить", callback_data="confirm_client_creation")
    builder.button(text="📝 Изменить ФИ", callback_data="edit_client_name_in_appointment")
    builder.button(text="📲 Изменить номер", callback_data="edit_client_phone_in_appointment")
    builder.button(text="❌ Отменить", callback_data="back_to_main_records")

    builder.adjust(1, 2, 1)

    return builder.as_markup()


def appointment_datetime_confirm_kb():
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Верно", callback_data="approve_datetime")
    builder.button(text="🔄 Изменить", callback_data="retry_datetime")
    builder.button(text="❌ Отменить", callback_data="back_to_main_records")

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def appointment_confirm_kb():
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Подтвердить", callback_data="approve_appointment_create")
    builder.button(text="📝 Заполнить заново", callback_data="restart_appointment_create")
    builder.button(text="❌ Отменить", callback_data="back_to_main_records")

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def back_to_records_kb():
    builder = InlineKeyboardBuilder()

    builder.button(text="⬅️ К записям", callback_data="back_to_main_records")

    builder.adjust(1)

    return builder.as_markup()
