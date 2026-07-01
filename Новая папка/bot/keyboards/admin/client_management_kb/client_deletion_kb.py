from aiogram.utils.keyboard import InlineKeyboardBuilder


def client_deletion_kb():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="Поиск по имени", callback_data="client_deletion_name"
    )

    builder.button(text="Поиск по номеру телефона", callback_data="client_deletion_phone")

    builder.button(text="Отменить удаление", callback_data="back_to_main_clients")

    builder.adjust(2, 1)

    return builder.as_markup()