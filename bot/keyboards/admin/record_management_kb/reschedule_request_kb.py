from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.record_management_kb.reschedule_request_cb import RescheduleRequestActionCB


def reschedule_request_kb(appointment_id: int) -> InlineKeyboardMarkup:
    """Accept / Reject buttons on a client's reschedule request."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Принять",
        callback_data=RescheduleRequestActionCB(action="accept", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text="❌ Отклонить",
        callback_data=RescheduleRequestActionCB(action="reject", appointment_id=appointment_id).pack(),
    )

    builder.adjust(1, 1)

    return builder.as_markup()
