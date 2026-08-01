from datetime import date

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import bot.messages.booking as msg
from bot.keyboards.client.booking_cb import (
    ClientBookDayCB,
    ClientBookDayPageCB,
    ClientBookDoctorCB,
    ClientBookSlotCB,
)
from bot.models.user import User

_WEEKDAY_LABELS = {
    "ru": ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"),
    "uz": ("Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"),
}


def _weekday_label(day: date, lang: str) -> str:
    labels = _WEEKDAY_LABELS.get(lang, _WEEKDAY_LABELS["ru"])
    return labels[day.weekday()]


def booking_cancel_kb(
    cancel_callback_data: str = "client_appointment_menu", lang: str = "ru"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=msg.cancel_label(lang), callback_data=cancel_callback_data)
    return builder.as_markup()


def booking_doctor_kb(
    staff_list: list[User], cancel_callback_data: str = "client_appointment_menu", lang: str = "ru"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for staff in staff_list:
        builder.button(
            text=staff.full_name,
            callback_data=ClientBookDoctorCB(staff_user_id=staff.ID).pack(),
        )
    rows = [1] * len(staff_list)

    builder.button(text=msg.cancel_label(lang), callback_data=cancel_callback_data)
    rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()


def booking_day_kb(
    days: list[date],
    week_offset: int,
    can_go_back: bool,
    can_go_forward: bool,
    cancel_callback_data: str = "client_appointment_menu",
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for day in days:
        label = f"{_weekday_label(day, lang)} {day.strftime('%d.%m')}"
        builder.button(
            text=label,
            callback_data=ClientBookDayCB(week_offset=week_offset, day_iso=day.isoformat()).pack(),
        )
    rows = [1] * len(days)

    nav_buttons = 0
    if can_go_back:
        builder.button(
            text=msg.day_back_label(lang),
            callback_data=ClientBookDayPageCB(week_offset=week_offset - 1).pack(),
        )
        nav_buttons += 1
    if can_go_forward:
        builder.button(
            text=msg.day_forward_label(lang),
            callback_data=ClientBookDayPageCB(week_offset=week_offset + 1).pack(),
        )
        nav_buttons += 1
    if nav_buttons:
        rows.append(nav_buttons)

    builder.button(text=msg.cancel_label(lang), callback_data=cancel_callback_data)
    rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()


def booking_slot_kb(
    slots: list[str], cancel_callback_data: str = "client_appointment_menu", lang: str = "ru"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for slot in slots:
        builder.button(text=slot, callback_data=ClientBookSlotCB(slot=slot).pack())

    rows = [4] * (len(slots) // 4)
    if len(slots) % 4:
        rows.append(len(slots) % 4)

    builder.button(text=msg.cancel_label(lang), callback_data=cancel_callback_data)
    rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()


def booking_confirm_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text=msg.confirm_submit_label(lang), callback_data="client_book_submit")
    builder.button(text=msg.confirm_restart_label(lang), callback_data="client_book_restart")
    builder.button(text=msg.cancel_label(lang), callback_data="client_appointment_menu")

    builder.adjust(1, 1, 1)

    return builder.as_markup()
