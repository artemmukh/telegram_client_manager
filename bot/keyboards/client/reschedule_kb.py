from datetime import date

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.client.reschedule_cb import (
    ClientRescheduleCancelCB,
    ClientRescheduleDayCB,
    ClientRescheduleDayPageCB,
    ClientRescheduleSlotCB,
    ClientRescheduleStartCB,
    ClientRescheduleSubmitCB,
)

_WEEKDAY_LABELS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def reschedule_day_kb(
    appointment_id: int, days: list[date], week_offset: int, can_go_back: bool, can_go_forward: bool
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for day in days:
        label = f"{_WEEKDAY_LABELS[day.weekday()]} {day.strftime('%d.%m')}"
        builder.button(
            text=label,
            callback_data=ClientRescheduleDayCB(
                appointment_id=appointment_id, week_offset=week_offset, day_iso=day.isoformat(),
            ).pack(),
        )
    rows = [1] * len(days)

    nav_buttons = 0
    if can_go_back:
        builder.button(
            text="⬅️ Назад",
            callback_data=ClientRescheduleDayPageCB(
                appointment_id=appointment_id, week_offset=week_offset - 1,
            ).pack(),
        )
        nav_buttons += 1
    if can_go_forward:
        builder.button(
            text="➡️ Дальше",
            callback_data=ClientRescheduleDayPageCB(
                appointment_id=appointment_id, week_offset=week_offset + 1,
            ).pack(),
        )
        nav_buttons += 1
    if nav_buttons:
        rows.append(nav_buttons)

    builder.button(
        text="❌ Отмена",
        callback_data=ClientRescheduleCancelCB(appointment_id=appointment_id).pack(),
    )
    rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()


def reschedule_slot_kb(appointment_id: int, slots: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for slot in slots:
        builder.button(
            text=slot,
            callback_data=ClientRescheduleSlotCB(appointment_id=appointment_id, slot=slot).pack(),
        )

    rows = [4] * (len(slots) // 4)
    if len(slots) % 4:
        rows.append(len(slots) % 4)

    builder.button(
        text="❌ Отмена",
        callback_data=ClientRescheduleCancelCB(appointment_id=appointment_id).pack(),
    )
    rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()


def reschedule_confirm_kb(appointment_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Отправить",
        callback_data=ClientRescheduleSubmitCB(appointment_id=appointment_id).pack(),
    )
    builder.button(
        text="✏️ Изменить",
        callback_data=ClientRescheduleStartCB(appointment_id=appointment_id).pack(),
    )
    builder.button(
        text="❌ Отмена",
        callback_data=ClientRescheduleCancelCB(appointment_id=appointment_id).pack(),
    )

    builder.adjust(1, 1, 1)

    return builder.as_markup()
