from aiogram.utils.keyboard import InlineKeyboardBuilder

def appointment_search_kb():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="👤 Поиск по имени", callback_data="appointment_full_name_search"
    )

    builder.button(text="📲 Поиск по номеру", callback_data="appointment_phone_search")

    builder.button(text="📋 Показать все записи", callback_data="get_all_appointments")

    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(2, 1, 1)

    return builder.as_markup()


def appointment_search_phone_kb():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить", callback_data="approve_appointment_search"
    )

    builder.button(text="📲 Изменить номер", callback_data="appointment_search_edit_phone")

    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1, 1, 1)

    return builder.as_markup()

def appointment_search_name_kb():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить", callback_data="approve_appointment_search"
    )

    builder.button(text="📝 Изменить ФИО", callback_data="appointment_search_edit_full_name")

    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1, 1, 1)

    return builder.as_markup()
