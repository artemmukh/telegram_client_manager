from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.record_management_kb.booking_request_cb import BookingRequestActionCB

_CONFIRM_LABEL = {"ru": "✅ Подтвердить", "uz": "✅ Tasdiqlash"}
_PROPOSE_OTHER_TIME_LABEL = {"ru": "🔁 Предложить другое время", "uz": "🔁 Boshqa vaqt taklif qilish"}
_REJECT_LABEL = {"ru": "❌ Отклонить", "uz": "❌ Rad etish"}
_CANCEL_LABEL = {"ru": "❌ Отменить", "uz": "❌ Bekor qilish"}
_RETRY_LABEL = {"ru": "🔄 Ввести заново", "uz": "🔄 Qaytadan kiritish"}


def booking_request_kb(appointment_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """Confirm / Propose-different-time / Reject buttons on a new self-booking request."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_CONFIRM_LABEL.get(lang, _CONFIRM_LABEL["ru"]),
        callback_data=BookingRequestActionCB(action="confirm", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text=_PROPOSE_OTHER_TIME_LABEL.get(lang, _PROPOSE_OTHER_TIME_LABEL["ru"]),
        callback_data=BookingRequestActionCB(action="propose", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text=_REJECT_LABEL.get(lang, _REJECT_LABEL["ru"]),
        callback_data=BookingRequestActionCB(action="reject", appointment_id=appointment_id).pack(),
    )

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def booking_request_propose_cancel_kb(appointment_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """Single "cancel" button - back to the request card without changes."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_CANCEL_LABEL.get(lang, _CANCEL_LABEL["ru"]),
        callback_data=BookingRequestActionCB(action="cancel_propose", appointment_id=appointment_id).pack(),
    )

    return builder.as_markup()


def booking_request_confirm_propose_kb(appointment_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_CONFIRM_LABEL.get(lang, _CONFIRM_LABEL["ru"]),
        callback_data=BookingRequestActionCB(action="approve_propose_datetime", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text=_RETRY_LABEL.get(lang, _RETRY_LABEL["ru"]),
        callback_data=BookingRequestActionCB(action="retry_propose_datetime", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text=_CANCEL_LABEL.get(lang, _CANCEL_LABEL["ru"]),
        callback_data=BookingRequestActionCB(action="cancel_propose", appointment_id=appointment_id).pack(),
    )

    builder.adjust(1, 1, 1)

    return builder.as_markup()
