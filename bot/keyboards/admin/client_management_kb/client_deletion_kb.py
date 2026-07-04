from aiogram.utils.keyboard import InlineKeyboardBuilder


def client_deletion_kb():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="👤 Поиск по имени", callback_data="client_full_name_deletion"
    )

    builder.button(text="📲 Поиск по номеру телефона", callback_data="client_phone_deletion")

    builder.button(text="❌ Отменить удаление", callback_data="cancel")

    builder.adjust(2, 1)

    return builder.as_markup()

def client_deletion_proceeding_kb():
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить удаление", callback_data="approve_deletion"
    )

    builder.button(text="❌ Отменить удаление", callback_data="cancel")

    builder.adjust(1, 1)

    return builder.as_markup()



from aiogram.utils.keyboard import InlineKeyboardBuilder

def choose_to_delete_user_kb(user_id: int):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="➡️ К Удалению",
        callback_data=f"delete:{user_id}",
    )

    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1,1)
    return builder.as_markup()



def client_search_to_delete_phone_kb():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить", callback_data="approve_client_delete"
    )


    builder.button(text="📲 Изменить номер", callback_data="client_search_to_delete_edit_phone")

    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1, 1, 1)


    return builder.as_markup()

def client_search_to_delete_name_kb():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить", callback_data="approve_client_delete"
    )

    builder.button(text="📝 Изменить ФИО", callback_data="client_search_to_delete_edit_full_name")


    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1, 1, 1)


    return builder.as_markup()



