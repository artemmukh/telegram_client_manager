from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.record_management_kb.reschedule_request_cb import RescheduleRequestActionCB


def reschedule_request_kb(appointment_id: int) -> InlineKeyboardMarkup:
    """Accept / Propose own time / Reject buttons on a client's reschedule request."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Принять",
        callback_data=RescheduleRequestActionCB(action="accept", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text="🔁 Предложить своё время",
        callback_data=RescheduleRequestActionCB(action="propose", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text="❌ Отклонить",
        callback_data=RescheduleRequestActionCB(action="reject", appointment_id=appointment_id).pack(),
    )

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def reschedule_request_propose_cancel_kb(appointment_id: int) -> InlineKeyboardMarkup:
    """Single "cancel" button - back to the request card without changes."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="❌ Отменить",
        callback_data=RescheduleRequestActionCB(action="cancel_propose", appointment_id=appointment_id).pack(),
    )

    return builder.as_markup()


def reschedule_request_confirm_propose_kb(appointment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить",
        callback_data=RescheduleRequestActionCB(
            action="approve_propose_datetime", appointment_id=appointment_id
        ).pack(),
    )
    builder.button(
        text="🔄 Ввести заново",
        callback_data=RescheduleRequestActionCB(
            action="retry_propose_datetime", appointment_id=appointment_id
        ).pack(),
    )
    builder.button(
        text="❌ Отменить",
        callback_data=RescheduleRequestActionCB(action="cancel_propose", appointment_id=appointment_id).pack(),
    )

    builder.adjust(1, 1, 1)

    return builder.as_markup()
