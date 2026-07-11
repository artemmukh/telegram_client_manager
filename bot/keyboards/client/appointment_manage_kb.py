from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.utils.client_utils.appointment_history_helpers import build_history_button_text
from bot.keyboards.client.appointment_manage_cb import (
    ClientManageActionCB,
    ClientManageCardCB,
    ClientManagePageCB,
)
from bot.keyboards.client.reschedule_cb import ClientRescheduleStartCB
from bot.models.appointment import Appointment
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.pagination import get_circular_page


def _add_status_action_buttons(
    builder: InlineKeyboardBuilder,
    can_cancel: bool,
    can_reschedule: bool,
    cancel_cb: CallbackData,
    reschedule_cb: CallbackData,
) -> int:
    button_rows = 0

    if can_cancel:
        builder.button(text="❌ Отменить", callback_data=cancel_cb.pack())
        button_rows += 1

    if can_reschedule:
        builder.button(text="🔁 Перенести", callback_data=reschedule_cb.pack())
        button_rows += 1

    return button_rows


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


def appointment_manage_card_kb(appointment: Appointment, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    button_rows = 0

    if appointment.proposed_datetime is not None and appointment.proposed_by == CreatedBy.ADMIN:
        # Client responds to the clinic's counter-offer (2b behavior).
        builder.button(
            text="✅ Согласен на новое время",
            callback_data=ClientManageActionCB(
                action="accept_proposal", appointment_id=appointment.id, page=page,
            ).pack(),
        )
        builder.button(
            text="❌ Не подходит",
            callback_data=ClientManageActionCB(
                action="reject_proposal", appointment_id=appointment.id, page=page,
            ).pack(),
        )
        button_rows += 2
    else:
        # Client's own reschedule request pending admin decision (proposed_by CLIENT)
        # only allows cancelling outright; a plain confirmed/pending appointment also
        # allows rescheduling.
        can_reschedule = appointment.status == AppointmentStatus.CONFIRMED and appointment.proposed_datetime is None

        button_rows += _add_status_action_buttons(
            builder,
            can_cancel=True,
            can_reschedule=can_reschedule,
            cancel_cb=ClientManageActionCB(action="cancel_ask", appointment_id=appointment.id, page=page),
            reschedule_cb=ClientRescheduleStartCB(appointment_id=appointment.id),
        )

    builder.button(
        text="⬅️ Назад к списку",
        callback_data=ClientManagePageCB(page=page).pack(),
    )
    button_rows += 1

    builder.adjust(*([1] * button_rows))

    return builder.as_markup()
