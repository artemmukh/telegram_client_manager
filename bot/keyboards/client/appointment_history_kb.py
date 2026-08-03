from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import bot.messages.booking as msg
from bot.handlers.utils.client_utils.appointment_history_helpers import build_history_button_text
from bot.keyboards.client.appointment_history_cb import (
    ClientHistoryActionCB,
    ClientHistoryCardCB,
    ClientHistoryPageCB,
)
from bot.keyboards.client.appointment_manage_kb import _add_status_action_buttons
from bot.keyboards.client.reschedule_cb import ClientRescheduleStartCB
from bot.models.appointment import Appointment
from bot.utils.appointment_enums import APPOINTMENT_TAB_ORDER, AppointmentStatus, tab_label
from bot.utils.pagination import get_circular_page

_TAB_STATUSES = {status.value: status for status in APPOINTMENT_TAB_ORDER}
_TAB_ORDER = [status.value for status in APPOINTMENT_TAB_ORDER]

_PAGE_LABEL = {
    "ru": "{page} из {total}",
    "uz": "{page} / {total}",
}

_GET_MEDICAL_RECORD_LABEL = {
    "ru": "📄 Получить историю болезни",
    "uz": "📄 Kasallik tarixini olish",
}

_ADD_DOCUMENT_LABEL = {
    "ru": "➕ Добавить документ",
    "uz": "➕ Hujjat qo'shish",
}

_BACK_TO_LIST_LABEL = {
    "ru": "⬅️ Назад к списку",
    "uz": "⬅️ Ro'yxatga qaytish",
}


def appointment_history_list_kb(
    items: list[Appointment],
    tab: str,
    current_page: int,
    total_pages: int,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for appointment in items:
        builder.button(
            text=build_history_button_text(appointment, lang),
            callback_data=ClientHistoryCardCB(appointment_id=appointment.id, tab=tab, page=current_page).pack(),
        )

    rows = [1] * len(items)

    for tab_value in _TAB_ORDER:
        label = tab_label(_TAB_STATUSES[tab_value], lang)
        text = f"• {label}" if tab_value == tab else label
        builder.button(text=text, callback_data=ClientHistoryPageCB(tab=tab_value, page=1).pack())
    rows += [3, 3]

    page_label = _PAGE_LABEL.get(lang, _PAGE_LABEL["ru"])

    if total_pages > 1:
        prev_page = get_circular_page(current_page, total_pages, "prev")
        next_page = get_circular_page(current_page, total_pages, "next")

        builder.button(text=page_label.format(page=current_page, total=total_pages), callback_data="noop")
        builder.button(text="⬅️", callback_data=ClientHistoryPageCB(tab=tab, page=prev_page).pack())
        builder.button(text="➡️", callback_data=ClientHistoryPageCB(tab=tab, page=next_page).pack())
        rows += [1, 2]
    else:
        builder.button(text=page_label.format(page=1, total=1), callback_data="noop")
        rows += [1]

    builder.button(text=msg.back_to_appointments_menu(lang), callback_data="client_appointment_menu")
    rows += [1]

    builder.adjust(*rows)
    return builder.as_markup()


def appointment_history_card_kb(
    appointment: Appointment,
    tab: str,
    page: int,
    can_cancel: bool,
    can_reschedule: bool,
    lang: str = "ru",
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
        lang=lang,
    )

    if appointment.status == AppointmentStatus.COMPLETED:
        builder.button(
            text=_GET_MEDICAL_RECORD_LABEL.get(lang, _GET_MEDICAL_RECORD_LABEL["ru"]),
            callback_data=ClientHistoryActionCB(
                action="get_medical_record", appointment_id=appointment.id, tab=tab, page=page,
            ).pack(),
        )
        button_rows += 1

        builder.button(
            text=_ADD_DOCUMENT_LABEL.get(lang, _ADD_DOCUMENT_LABEL["ru"]),
            callback_data=ClientHistoryActionCB(
                action="add_medical_record", appointment_id=appointment.id, tab=tab, page=page,
            ).pack(),
        )
        button_rows += 1

    builder.button(
        text=_BACK_TO_LIST_LABEL.get(lang, _BACK_TO_LIST_LABEL["ru"]),
        callback_data=ClientHistoryPageCB(tab=tab, page=page).pack(),
    )
    button_rows += 1

    builder.adjust(*([1] * button_rows))
    return builder.as_markup()
