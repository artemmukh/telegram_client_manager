from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.utils.client_utils.appointment_history_helpers import build_history_button_text
from bot.keyboards.client.appointment_history_cb import ClientHistoryCardCB, ClientHistoryPageCB
from bot.models.appointment import Appointment
from bot.utils.pagination import get_circular_page

_TAB_LABELS = {
    "upcoming": "Предстоящие",
    "past": "Прошедшие",
    "all": "Все",
}


def appointment_history_list_kb(
    items: list[Appointment],
    tab: str,
    current_page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for appointment in items:
        builder.button(
            text=build_history_button_text(appointment),
            callback_data=ClientHistoryCardCB(appointment_id=appointment.id, tab=tab, page=current_page).pack(),
        )

    rows = [1] * len(items)

    for tab_value, label in _TAB_LABELS.items():
        text = f"• {label}" if tab_value == tab else label
        builder.button(text=text, callback_data=ClientHistoryPageCB(tab=tab_value, page=1).pack())
    rows.append(3)

    if total_pages > 1:
        prev_page = get_circular_page(current_page, total_pages, "prev")
        next_page = get_circular_page(current_page, total_pages, "next")

        builder.button(text=f"{current_page} из {total_pages}", callback_data="noop")
        builder.button(text="⬅️", callback_data=ClientHistoryPageCB(tab=tab, page=prev_page).pack())
        builder.button(text="➡️", callback_data=ClientHistoryPageCB(tab=tab, page=next_page).pack())
        rows += [1, 2]
    else:
        builder.button(text="Страница 1 из 1", callback_data="noop")
        rows += [1]

    builder.button(text="⬅️ К меню записей", callback_data="client_appointment_menu")
    rows += [1]

    builder.adjust(*rows)
    return builder.as_markup()


def appointment_history_card_kb(tab: str, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Назад к списку",
        callback_data=ClientHistoryPageCB(tab=tab, page=page).pack(),
    )
    return builder.as_markup()
