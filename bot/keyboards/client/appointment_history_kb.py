from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.utils.client_utils.appointment_history_helpers import build_history_button_text
from bot.keyboards.client.appointment_history_cb import (
    ClientHistoryActionCB,
    ClientHistoryCardCB,
    ClientHistoryPageCB,
)
from bot.keyboards.client.appointment_manage_kb import _add_status_action_buttons
from bot.keyboards.client.reschedule_cb import ClientRescheduleStartCB
from bot.models.appointment import Appointment
from bot.utils.appointment_enums import APPOINTMENT_TAB_LABELS, APPOINTMENT_TAB_ORDER, AppointmentStatus
from bot.utils.pagination import get_circular_page

_TAB_LABELS = {status.value: label for status, label in APPOINTMENT_TAB_LABELS.items()}
_TAB_ORDER = [status.value for status in APPOINTMENT_TAB_ORDER]


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

    for tab_value in _TAB_ORDER:
        label = _TAB_LABELS[tab_value]
        text = f"• {label}" if tab_value == tab else label
        builder.button(text=text, callback_data=ClientHistoryPageCB(tab=tab_value, page=1).pack())
    rows += [3, 3]

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


def appointment_history_card_kb(
    appointment: Appointment,
    tab: str,
    page: int,
    can_cancel: bool,
    can_reschedule: bool,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    button_rows = _add_status_action_buttons(
        builder,
        can_cancel=can_cancel,
        can_reschedule=can_reschedule,
        cancel_cb=ClientHistoryActionCB(
            action="cancel_ask", appointment_id=appointment.id, tab=tab, page=page,
        ),
        reschedule_cb=ClientRescheduleStartCB(appointment_id=appointment.id),
    )

    if appointment.status == AppointmentStatus.COMPLETED:
        builder.button(
            text="📄 Получить историю болезни",
            callback_data=ClientHistoryActionCB(
                action="get_medical_record", appointment_id=appointment.id, tab=tab, page=page,
            ).pack(),
        )
        button_rows += 1

    builder.button(
        text="⬅️ Назад к списку",
        callback_data=ClientHistoryPageCB(tab=tab, page=page).pack(),
    )
    button_rows += 1

    builder.adjust(*([1] * button_rows))
    return builder.as_markup()
