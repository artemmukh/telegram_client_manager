from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.utils.client_utils.appointment_history_helpers import build_history_button_text
from bot.keyboards.client.appointment_manage_cb import (
    ClientManageActionCB,
    ClientManageCardCB,
    ClientManagePageCB,
)
from bot.models.appointment import Appointment
from bot.utils.pagination import get_circular_page


def appointment_manage_list_kb(
    items: list[Appointment],
    current_page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for appointment in items:
        builder.button(
            text=build_history_button_text(appointment),
            callback_data=ClientManageCardCB(appointment_id=appointment.id, page=current_page).pack(),
        )

    rows = [1] * len(items)

    if total_pages > 1:
        prev_page = get_circular_page(current_page, total_pages, "prev")
        next_page = get_circular_page(current_page, total_pages, "next")

        builder.button(text=f"{current_page} из {total_pages}", callback_data="noop")
        builder.button(text="⬅️", callback_data=ClientManagePageCB(page=prev_page).pack())
        builder.button(text="➡️", callback_data=ClientManagePageCB(page=next_page).pack())
        rows += [1, 2]
    else:
        builder.button(text="Страница 1 из 1", callback_data="noop")
        rows += [1]

    builder.button(text="⬅️ К меню записей", callback_data="client_appointment_menu")
    rows += [1]

    builder.adjust(*rows)
    return builder.as_markup()


def appointment_manage_empty_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ К меню записей", callback_data="client_appointment_menu")
    return builder.as_markup()


def appointment_manage_card_kb(appointment_id: int, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвержу приход",
        callback_data=ClientManageActionCB(action="confirm", appointment_id=appointment_id, page=page).pack(),
    )
    builder.button(
        text="❌ Отменить",
        callback_data=ClientManageActionCB(action="cancel_ask", appointment_id=appointment_id, page=page).pack(),
    )
    builder.button(
        text="⬅️ Назад к списку",
        callback_data=ClientManagePageCB(page=page).pack(),
    )

    builder.adjust(1, 1, 1)

    return builder.as_markup()
