from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import bot.messages.booking as msg
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


_PAGE_LABEL = {
    "ru": "{page} из {total}",
    "uz": "{page} / {total}",
}

_CANCEL_ACTION_LABEL = {
    "ru": "❌ Отменить",
    "uz": "❌ Bekor qilish",
}

_RESCHEDULE_ACTION_LABEL = {
    "ru": "🔁 Перенести",
    "uz": "🔁 Ko'chirish",
}

_ACCEPT_PROPOSAL_LABEL = {
    "ru": "✅ Согласен на новое время",
    "uz": "✅ Yangi vaqtga roziman",
}

_REJECT_PROPOSAL_LABEL = {
    "ru": "❌ Не подходит",
    "uz": "❌ Mos kelmaydi",
}

_BACK_TO_LIST_LABEL = {
    "ru": "⬅️ Назад к списку",
    "uz": "⬅️ Ro'yxatga qaytish",
}


def _add_status_action_buttons(
    builder: InlineKeyboardBuilder,
    can_cancel: bool,
    can_reschedule: bool,
    cancel_cb: CallbackData,
    reschedule_cb: CallbackData,
    lang: str = "ru",
) -> int:
    button_rows = 0

    if can_cancel:
        builder.button(text=_CANCEL_ACTION_LABEL.get(lang, _CANCEL_ACTION_LABEL["ru"]), callback_data=cancel_cb.pack())
        button_rows += 1

    if can_reschedule:
        builder.button(
            text=_RESCHEDULE_ACTION_LABEL.get(lang, _RESCHEDULE_ACTION_LABEL["ru"]), callback_data=reschedule_cb.pack()
        )
        button_rows += 1

    return button_rows


def appointment_manage_list_kb(
    items: list[Appointment],
    current_page: int,
    total_pages: int,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for appointment in items:
        builder.button(
            text=build_history_button_text(appointment),
            callback_data=ClientManageCardCB(appointment_id=appointment.id, page=current_page).pack(),
        )

    rows = [1] * len(items)
    page_label = _PAGE_LABEL.get(lang, _PAGE_LABEL["ru"])

    if total_pages > 1:
        prev_page = get_circular_page(current_page, total_pages, "prev")
        next_page = get_circular_page(current_page, total_pages, "next")

        builder.button(text=page_label.format(page=current_page, total=total_pages), callback_data="noop")
        builder.button(text="⬅️", callback_data=ClientManagePageCB(page=prev_page).pack())
        builder.button(text="➡️", callback_data=ClientManagePageCB(page=next_page).pack())
        rows += [1, 2]
    else:
        builder.button(text=page_label.format(page=1, total=1), callback_data="noop")
        rows += [1]

    builder.button(text=msg.back_to_appointments_menu(lang), callback_data="client_appointment_menu")
    rows += [1]

    builder.adjust(*rows)
    return builder.as_markup()


def appointment_manage_empty_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=msg.back_to_appointments_menu(lang), callback_data="client_appointment_menu")
    return builder.as_markup()


def appointment_manage_card_kb(appointment: Appointment, page: int, lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    button_rows = 0

    if appointment.proposed_datetime is not None and appointment.proposed_by == CreatedBy.ADMIN:
        # Client responds to the clinic's counter-offer (2b behavior).
        builder.button(
            text=_ACCEPT_PROPOSAL_LABEL.get(lang, _ACCEPT_PROPOSAL_LABEL["ru"]),
            callback_data=ClientManageActionCB(
                action="accept_proposal", appointment_id=appointment.id, page=page,
            ).pack(),
        )
        builder.button(
            text=_REJECT_PROPOSAL_LABEL.get(lang, _REJECT_PROPOSAL_LABEL["ru"]),
            callback_data=ClientManageActionCB(
                action="reject_proposal", appointment_id=appointment.id, page=page,
            ).pack(),
        )
        button_rows += 2
    else:
        # Client's own reschedule request pending admin decision (proposed_by CLIENT)
        # only allows cancelling outright; a plain confirmed/pending appointment also
        # allows rescheduling.
        can_reschedule = (
            appointment.proposed_datetime is None
            and (
                appointment.status == AppointmentStatus.CONFIRMED
                or (appointment.status == AppointmentStatus.PENDING and appointment.created_by == CreatedBy.CLIENT)
            )
        )

        button_rows += _add_status_action_buttons(
            builder,
            can_cancel=True,
            can_reschedule=can_reschedule,
            cancel_cb=ClientManageActionCB(action="cancel_ask", appointment_id=appointment.id, page=page),
            reschedule_cb=ClientRescheduleStartCB(appointment_id=appointment.id),
            lang=lang,
        )

    builder.button(
        text=_BACK_TO_LIST_LABEL.get(lang, _BACK_TO_LIST_LABEL["ru"]),
        callback_data=ClientManagePageCB(page=page).pack(),
    )
    button_rows += 1

    builder.adjust(*([1] * button_rows))

    return builder.as_markup()
