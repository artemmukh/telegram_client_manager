from aiogram.utils.keyboard import InlineKeyboardBuilder


def client_update_kb():

    builder = InlineKeyboardBuilder()

    builder.button(text="🔍 Поиск по имени", callback_data="client_full_name_update")

    builder.button(text="📞 Поиск по номеру", callback_data="client_phone_update")

    builder.button(text="👥 Показать всех клиентов", callback_data="get_all_clients_for_update")

    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(2, 1, 1)

    return builder.as_markup()


def client_search_to_update_name_kb():

    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Подтвердить", callback_data="approve_client_update_search")

    builder.button(text="📝 Изменить ФИО", callback_data="client_search_to_update_edit_full_name")

    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def client_search_to_update_phone_kb():

    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Подтвердить", callback_data="approve_client_update_search")

    builder.button(text="📲 Изменить номер", callback_data="client_search_to_update_edit_phone")

    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def choose_to_update_user_kb(user_id: int):

    builder = InlineKeyboardBuilder()

    builder.button(text="✏️ Изменить ФИО", callback_data=f"update_name:{user_id}")

    builder.button(text="📞 Изменить телефон", callback_data=f"update_phone:{user_id}")

    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(2, 1)

    return builder.as_markup()


def confirm_new_full_name_kb():

    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Подтвердить", callback_data="approve_update_name")

    builder.button(text="📝 Ввести заново", callback_data="edit_new_full_name")

    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def confirm_new_phone_kb():

    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Подтвердить", callback_data="approve_update_phone")

    builder.button(text="📲 Ввести заново", callback_data="edit_new_phone")

    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1, 1, 1)

    return builder.as_markup()
