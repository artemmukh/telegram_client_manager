from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.client.appointment_invite_cb import AppointmentInviteActionCB
from bot.keyboards.client.appointment_manage_cb import ClientManageActionCB
from bot.keyboards.client.reschedule_cb import ClientRescheduleStartCB

_WILL_COME_LABEL = {
    "ru": "✅ Приду",
    "uz": "✅ Boraman",
}

_WONT_COME_LABEL = {
    "ru": "❌ Не приду",
    "uz": "❌ Bormayman",
}

_CONFIRM_LABEL = {
    "ru": "✅ Подтвердить",
    "uz": "✅ Tasdiqlash",
}

_PROPOSE_OWN_TIME_LABEL = {
    "ru": "🔁 Предложить своё время",
    "uz": "🔁 O'z vaqtimni taklif qilish",
}

_CANCEL_INVITE_LABEL = {
    "ru": "❌ Отменить",
    "uz": "❌ Bekor qilish",
}

_ACCEPT_NEW_TIME_LABEL = {
    "ru": "✅ Согласен на новое время",
    "uz": "✅ Yangi vaqtga roziman",
}

_REJECT_NEW_TIME_LABEL = {
    "ru": "❌ Не подходит",
    "uz": "❌ Mos kelmaydi",
}

_CONFIRM_CANCEL_LABEL = {
    "ru": "✅ Да, отменить",
    "uz": "✅ Ha, bekor qilish",
}

_DECLINE_CANCEL_LABEL = {
    "ru": "❌ Нет, вернуться",
    "uz": "❌ Yo'q, ortga qaytish",
}


def appointment_response_kb(appointment_id: int, lang: str = "ru"):
    """Keyboard for client appointment response (Confirm/Cancel)."""
    builder = InlineKeyboardBuilder()

    builder.button(text=_WILL_COME_LABEL.get(lang, _WILL_COME_LABEL["ru"]), callback_data=f"appt_confirm:{appointment_id}")
    builder.button(text=_WONT_COME_LABEL.get(lang, _WONT_COME_LABEL["ru"]), callback_data=f"appt_cancel:{appointment_id}")

    builder.adjust(1, 1)

    return builder.as_markup()


def appointment_invite_kb(appointment_id: int, lang: str = "ru"):
    """3-кнопочный ответ клиента на первоначальное приглашение (или просмотр деталей
    PENDING-записи, admin-created): Подтвердить / Предложить своё время / Отменить."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_CONFIRM_LABEL.get(lang, _CONFIRM_LABEL["ru"]),
        callback_data=AppointmentInviteActionCB(action="confirm", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text=_PROPOSE_OWN_TIME_LABEL.get(lang, _PROPOSE_OWN_TIME_LABEL["ru"]),
        callback_data=ClientRescheduleStartCB(appointment_id=appointment_id).pack(),
    )
    builder.button(
        text=_CANCEL_INVITE_LABEL.get(lang, _CANCEL_INVITE_LABEL["ru"]),
        callback_data=AppointmentInviteActionCB(action="cancel", appointment_id=appointment_id).pack(),
    )
    builder.adjust(1, 1, 1)

    return builder.as_markup()


def appointment_reminder_details_kb(appointment_id: int, lang: str = "ru"):
    """Keyboard for the 24h reminder (Details only)."""
    builder = InlineKeyboardBuilder()

    # CLAUDE DONT TOUCH COMMENTS
    # builder.button(text="📋 Детали записи", callback_data=f"appt_details:{appointment_id}")

    builder.adjust(1)

    return builder.as_markup()


def appointment_reminder_with_buttons_kb(appointment_id: int, lang: str = "ru"):
    """Keyboard for the 2h reminder (Confirm/Cancel/Details)."""
    builder = InlineKeyboardBuilder()

    builder.button(text=_WILL_COME_LABEL.get(lang, _WILL_COME_LABEL["ru"]), callback_data=f"appt_confirm:{appointment_id}")
    builder.button(text=_WONT_COME_LABEL.get(lang, _WONT_COME_LABEL["ru"]), callback_data=f"appt_cancel:{appointment_id}")
    # CLAUDE DONT TOUCH COMMENTS
    # builder.button(text="📋 Детали записи", callback_data=f"appt_details:{appointment_id}")

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def reschedule_proposal_kb(appointment_id: int, lang: str = "ru"):
    """Keyboard for client response to a clinic-proposed new time (Accept/Reject)."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_ACCEPT_NEW_TIME_LABEL.get(lang, _ACCEPT_NEW_TIME_LABEL["ru"]),
        callback_data=ClientManageActionCB(action="accept_proposal", appointment_id=appointment_id, page=1).pack(),
    )
    builder.button(
        text=_REJECT_NEW_TIME_LABEL.get(lang, _REJECT_NEW_TIME_LABEL["ru"]),
        callback_data=ClientManageActionCB(action="reject_proposal", appointment_id=appointment_id, page=1).pack(),
    )

    builder.adjust(1, 1)

    return builder.as_markup()


def cancel_confirmation_kb(yes_callback: str, no_callback: str, lang: str = "ru"):
    """Keyboard for cancellation confirmation dialog."""
    builder = InlineKeyboardBuilder()

    builder.button(text=_CONFIRM_CANCEL_LABEL.get(lang, _CONFIRM_CANCEL_LABEL["ru"]), callback_data=yes_callback)
    builder.button(text=_DECLINE_CANCEL_LABEL.get(lang, _DECLINE_CANCEL_LABEL["ru"]), callback_data=no_callback)

    builder.adjust(1, 1)

    return builder.as_markup()
