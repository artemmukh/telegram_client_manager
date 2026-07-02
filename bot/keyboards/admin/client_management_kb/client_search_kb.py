from aiogram.utils.keyboard import InlineKeyboardBuilder

def client_search_kb():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="👤 Поиск по имени", callback_data="client_full_name_search"
    )

    builder.button(text="📲 Поиск по номеру", callback_data="client_phone_search")

    builder.button(text="👥 Показать всех клиентов", callback_data="get_all_clients")

    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust( 2, 1, 1)

    return builder.as_markup()


def client_search_phone_kb():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить", callback_data="approve_client_search"
    )


    builder.button(text="📲 Изменить номер", callback_data="client_search_edit_phone")

    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1, 1, 1)


    return builder.as_markup()

def client_search_name_kb():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить", callback_data="approve_client_search"
    )

    builder.button(text="📝 Изменить ФИО", callback_data="client_search_edit_full_name")


    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1, 1, 1)


    return builder.as_markup()
