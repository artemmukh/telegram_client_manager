from aiogram.utils.keyboard import InlineKeyboardBuilder

_CONFIRM_LABEL = {
    "ru": "✅ Подтвердить",
    "uz": "✅ Tasdiqlash",
}

_EDIT_NAME_LABEL = {
    "ru": "📝 Изменить ФИ",
    "uz": "📝 F.I.Sh.ni o'zgartirish",
}

_EDIT_PHONE_LABEL = {
    "ru": "📲 Изменить номер",
    "uz": "📲 Raqamni o'zgartirish",
}

_CANCEL_LABEL = {
    "ru": "❌ Отменить",
    "uz": "❌ Bekor qilish",
}

_CORRECT_LABEL = {
    "ru": "✅ Верно",
    "uz": "✅ To'g'ri",
}

_CHANGE_LABEL = {
    "ru": "🔄 Изменить",
    "uz": "🔄 O'zgartirish",
}

_FILL_AGAIN_LABEL = {
    "ru": "📝 Заполнить заново",
    "uz": "📝 Qaytadan to'ldirish",
}

_BACK_TO_RECORDS_LABEL = {
    "ru": "⬅️ К записям",
    "uz": "⬅️ Yozuvlarga",
}


def client_creation_confirm_kb(lang: str = "ru"):
    builder = InlineKeyboardBuilder()

    builder.button(text=_CONFIRM_LABEL.get(lang, _CONFIRM_LABEL["ru"]), callback_data="confirm_client_creation")
    builder.button(text=_EDIT_NAME_LABEL.get(lang, _EDIT_NAME_LABEL["ru"]), callback_data="edit_client_name_in_appointment")
    builder.button(text=_EDIT_PHONE_LABEL.get(lang, _EDIT_PHONE_LABEL["ru"]), callback_data="edit_client_phone_in_appointment")
    builder.button(text=_CANCEL_LABEL.get(lang, _CANCEL_LABEL["ru"]), callback_data="back_to_main_records")

    builder.adjust(1, 2, 1)

    return builder.as_markup()


def appointment_datetime_confirm_kb(lang: str = "ru"):
    builder = InlineKeyboardBuilder()

    builder.button(text=_CORRECT_LABEL.get(lang, _CORRECT_LABEL["ru"]), callback_data="approve_datetime")
    builder.button(text=_CHANGE_LABEL.get(lang, _CHANGE_LABEL["ru"]), callback_data="retry_datetime")
    builder.button(text=_CANCEL_LABEL.get(lang, _CANCEL_LABEL["ru"]), callback_data="back_to_main_records")

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def appointment_confirm_kb(lang: str = "ru"):
    builder = InlineKeyboardBuilder()

    builder.button(text=_CONFIRM_LABEL.get(lang, _CONFIRM_LABEL["ru"]), callback_data="approve_appointment_create")
    builder.button(text=_FILL_AGAIN_LABEL.get(lang, _FILL_AGAIN_LABEL["ru"]), callback_data="restart_appointment_create")
    builder.button(text=_CANCEL_LABEL.get(lang, _CANCEL_LABEL["ru"]), callback_data="back_to_main_records")

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def back_to_records_kb(lang: str = "ru"):
    builder = InlineKeyboardBuilder()

    builder.button(text=_BACK_TO_RECORDS_LABEL.get(lang, _BACK_TO_RECORDS_LABEL["ru"]), callback_data="back_to_main_records")

    builder.adjust(1)

    return builder.as_markup()
