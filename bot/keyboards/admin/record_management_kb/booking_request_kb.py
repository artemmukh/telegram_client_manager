from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.record_management_kb.booking_request_cb import BookingRequestActionCB


def booking_request_kb(appointment_id: int) -> InlineKeyboardMarkup:
    """Confirm / Propose-different-time / Reject buttons on a new self-booking request."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить",
        callback_data=BookingRequestActionCB(action="confirm", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text="🔁 Предложить другое время",
        callback_data=BookingRequestActionCB(action="propose", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text="❌ Отклонить",
        callback_data=BookingRequestActionCB(action="reject", appointment_id=appointment_id).pack(),
    )

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def booking_request_propose_cancel_kb(appointment_id: int) -> InlineKeyboardMarkup:
    """Single "cancel" button - back to the request card without changes."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="❌ Отменить",
        callback_data=BookingRequestActionCB(action="cancel_propose", appointment_id=appointment_id).pack(),
    )

    return builder.as_markup()


def booking_request_confirm_propose_kb(appointment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить",
        callback_data=BookingRequestActionCB(action="approve_propose_datetime", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text="🔄 Ввести заново",
        callback_data=BookingRequestActionCB(action="retry_propose_datetime", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text="❌ Отменить",
        callback_data=BookingRequestActionCB(action="cancel_propose", appointment_id=appointment_id).pack(),
    )

    builder.adjust(1, 1, 1)

    return builder.as_markup()
