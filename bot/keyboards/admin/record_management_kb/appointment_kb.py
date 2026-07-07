from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.utils.appointment_enums import AppointmentStatus


def appointment_datetime_confirm_kb():
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Верно", callback_data="approve_datetime")
    builder.button(text="🔄 Изменить", callback_data="retry_datetime")
    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def appointment_confirm_kb():
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Подтвердить", callback_data="approve_appointment_create")
    builder.button(text="📝 Заполнить заново", callback_data="restart_appointment_create")
    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1, 1, 1)

    return builder.as_markup()


def choose_appointment_to_delete_kb(appointment_id: int):
    builder = InlineKeyboardBuilder()

    builder.button(text="🗑 Удалить", callback_data=f"appt_delete:{appointment_id}")

    builder.adjust(1)

    return builder.as_markup()


def appointment_delete_confirm_kb(appointment_id: int):
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Подтвердить удаление", callback_data=f"appt_approve_delete:{appointment_id}")
    builder.button(text="❌ Отменить", callback_data="cancel")

    builder.adjust(1, 1)

    return builder.as_markup()


def appointment_update_menu_kb(appointment_id: int):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить",
        callback_data=f"appt_status:{appointment_id}:{AppointmentStatus.CONFIRMED.value}",
    )
    builder.button(
        text="🚫 Отменить запись",
        callback_data=f"appt_status:{appointment_id}:{AppointmentStatus.CANCELLED.value}",
    )
    builder.button(
        text="✔️ Завершена",
        callback_data=f"appt_status:{appointment_id}:{AppointmentStatus.COMPLETED.value}",
    )
    builder.button(
        text="🙅 Неявка",
        callback_data=f"appt_status:{appointment_id}:{AppointmentStatus.NO_SHOW.value}",
    )
    builder.button(text="🕐 Изменить время", callback_data=f"appt_edit_dt:{appointment_id}")
    builder.button(text="📝 Изменить услугу", callback_data=f"appt_edit_purpose:{appointment_id}")

    builder.adjust(2, 2, 2)

    return builder.as_markup()


def back_to_records_kb():
    builder = InlineKeyboardBuilder()

    builder.button(text="⬅️ К записям", callback_data="back_to_main_records")

    builder.adjust(1)

    return builder.as_markup()
