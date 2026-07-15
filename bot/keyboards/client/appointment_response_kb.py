from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.client.appointment_invite_cb import AppointmentInviteActionCB
from bot.keyboards.client.appointment_manage_cb import ClientManageActionCB
from bot.keyboards.client.reschedule_cb import ClientRescheduleStartCB


def appointment_response_kb(appointment_id: int):
    """Keyboard for client appointment response (Confirm/Cancel)."""
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Приду", callback_data=f"appt_confirm:{appointment_id}")
    builder.button(text="❌ Не приду", callback_data=f"appt_cancel:{appointment_id}")

    builder.adjust(1, 1)

    return builder.as_markup()


def appointment_invite_kb(appointment_id: int):
    """3-кнопочный ответ клиента на первоначальное приглашение (или просмотр деталей
    PENDING-записи, admin-created): Подтвердить / Предложить своё время / Отменить."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить",
        callback_data=AppointmentInviteActionCB(action="confirm", appointment_id=appointment_id).pack(),
    )
    builder.button(
        text="🔁 Предложить своё время",
        callback_data=ClientRescheduleStartCB(appointment_id=appointment_id).pack(),
    )
    builder.button(
        text="❌ Отменить",
        callback_data=AppointmentInviteActionCB(action="cancel", appointment_id=appointment_id).pack(),
    )
    builder.adjust(1, 1, 1)

    return builder.as_markup()


def appointment_reminder_details_kb(appointment_id: int):
    """Keyboard for the 24h reminder (Details only)."""
    builder = InlineKeyboardBuilder()

    # CLAUDE DONT TOUCH COMMENTS
    # builder.button(text="📋 Детали записи", callback_data=f"appt_details:{appointment_id}")

    builder.adjust(1)

    return builder.as_markup()


def appointment_reminder_with_buttons_kb(appointment_id: int):
    """Keyboard for the 2h reminder (Confirm/Cancel/Details)."""
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Приду", callback_data=f"appt_confirm:{appointment_id}")
    builder.button(text="❌ Не приду", callback_data=f"appt_cancel:{appointment_id}")
    # CLAUDE DONT TOUCH COMMENTS
    # builder.button(text="📋 Детали записи", callback_data=f"appt_details:{appointment_id}")

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def reschedule_proposal_kb(appointment_id: int):
    """Keyboard for client response to a clinic-proposed new time (Accept/Reject)."""
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Согласен на новое время",
        callback_data=ClientManageActionCB(action="accept_proposal", appointment_id=appointment_id, page=1).pack(),
    )
    builder.button(
        text="❌ Не подходит",
        callback_data=ClientManageActionCB(action="reject_proposal", appointment_id=appointment_id, page=1).pack(),
    )

    builder.adjust(1, 1)

    return builder.as_markup()


def cancel_confirmation_kb(yes_callback: str, no_callback: str):
    """Keyboard for cancellation confirmation dialog."""
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Да, отменить", callback_data=yes_callback)
    builder.button(text="❌ Нет, вернуться", callback_data=no_callback)

    builder.adjust(1, 1)

    return builder.as_markup()
