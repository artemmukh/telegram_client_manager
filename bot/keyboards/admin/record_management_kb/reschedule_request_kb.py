from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.record_management_kb.reschedule_request_cb import RescheduleRequestActionCB

_ACCEPT_LABEL = {"ru": "✅ Принять", "uz": "✅ Qabul qilish"}
_PROPOSE_OWN_TIME_LABEL = {"ru": "🔁 Предложить своё время", "uz": "🔁 O'z vaqtini taklif qilish"}
_REJECT_LABEL = {"ru": "❌ Отклонить", "uz": "❌ Rad etish"}
_CANCEL_LABEL = {"ru": "❌ Отменить", "uz": "❌ Bekor qilish"}
_CONFIRM_LABEL = {"ru": "✅ Подтвердить", "uz": "✅ Tasdiqlash"}
_RETRY_LABEL = {"ru": "🔄 Ввести заново", "uz": "🔄 Qaytadan kiritish"}


def reschedule_request_kb(appointment_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """Accept / Propose own time / Reject buttons on a client's reschedule request."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_ACCEPT_LABEL.get(lang, _ACCEPT_LABEL["ru"]),
        callback_data=RescheduleRequestActionCB(action="accept", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text=_PROPOSE_OWN_TIME_LABEL.get(lang, _PROPOSE_OWN_TIME_LABEL["ru"]),
        callback_data=RescheduleRequestActionCB(action="propose", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text=_REJECT_LABEL.get(lang, _REJECT_LABEL["ru"]),
        callback_data=RescheduleRequestActionCB(action="reject", appointment_id=appointment_id).pack(),
    )

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def reschedule_request_propose_cancel_kb(appointment_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """Single "cancel" button - back to the request card without changes."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_CANCEL_LABEL.get(lang, _CANCEL_LABEL["ru"]),
        callback_data=RescheduleRequestActionCB(action="cancel_propose", appointment_id=appointment_id).pack(),
    )

    return builder.as_markup()


def reschedule_request_confirm_propose_kb(appointment_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_CONFIRM_LABEL.get(lang, _CONFIRM_LABEL["ru"]),
        callback_data=RescheduleRequestActionCB(
            action="approve_propose_datetime", appointment_id=appointment_id
        ).pack(),
    )
    builder.button(
        text=_RETRY_LABEL.get(lang, _RETRY_LABEL["ru"]),
        callback_data=RescheduleRequestActionCB(
            action="retry_propose_datetime", appointment_id=appointment_id
        ).pack(),
    )
    builder.button(
        text=_CANCEL_LABEL.get(lang, _CANCEL_LABEL["ru"]),
        callback_data=RescheduleRequestActionCB(action="cancel_propose", appointment_id=appointment_id).pack(),
    )

    builder.adjust(1, 1, 1)

    return builder.as_markup()
