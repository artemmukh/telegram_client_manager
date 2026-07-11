from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.record_management_kb.completion_followup_cb import CompletionFollowupCB


def completion_followup_kb(appointment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Да",
        callback_data=CompletionFollowupCB(action="edit", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text="❌ Нет",
        callback_data=CompletionFollowupCB(action="skip", appointment_id=appointment_id).pack(),
    )

    builder.adjust(2)

    return builder.as_markup()
