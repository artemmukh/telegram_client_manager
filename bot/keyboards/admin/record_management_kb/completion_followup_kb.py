from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.record_management_kb.completion_followup_cb import CompletionFollowupCB

_YES_FINISH_LABEL = {
    "ru": "✅ Да, завершить",
    "uz": "✅ Ha, yakunlash",
}

_NO_CORRECT_LABEL = {
    "ru": "❌ Нет, всё верно",
    "uz": "❌ Yo'q, hammasi to'g'ri",
}


def completion_followup_kb(appointment_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_YES_FINISH_LABEL.get(lang, _YES_FINISH_LABEL["ru"]),
        callback_data=CompletionFollowupCB(action="edit", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text=_NO_CORRECT_LABEL.get(lang, _NO_CORRECT_LABEL["ru"]),
        callback_data=CompletionFollowupCB(action="skip", appointment_id=appointment_id).pack(),
    )

    builder.adjust(2)

    return builder.as_markup()
