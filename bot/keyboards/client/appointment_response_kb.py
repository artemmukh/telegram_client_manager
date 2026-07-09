from aiogram.utils.keyboard import InlineKeyboardBuilder


def appointment_response_kb(appointment_id: int):
    """Keyboard for client appointment response (Confirm/Cancel)."""
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Приду", callback_data=f"appt_confirm:{appointment_id}")
    builder.button(text="❌ Не приду", callback_data=f"appt_cancel:{appointment_id}")

    builder.adjust(1, 1)

    return builder.as_markup()


def cancel_confirmation_kb(yes_callback: str, no_callback: str):
    """Keyboard for cancellation confirmation dialog."""
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Да, отменить", callback_data=yes_callback)
    builder.button(text="❌ Нет, вернуться", callback_data=no_callback)

    builder.adjust(1, 1)

    return builder.as_markup()
