from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.utils.admin_utils.appointment_browser_helpers import build_appointment_button_text
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import (
    ApptActionCB,
    ApptCardCB,
    ApptPageCB,
)
from bot.models.appointment import Appointment
from bot.utils.appointment_enums import APPOINTMENT_TAB_LABELS, APPOINTMENT_TAB_ORDER, AppointmentStatus
from bot.utils.pagination import get_circular_page

_TAB_LABELS = {status.value: label for status, label in APPOINTMENT_TAB_LABELS.items()}
_TAB_ORDER = [status.value for status in APPOINTMENT_TAB_ORDER]

_STATUS_ACTION_BUTTONS = [
    (AppointmentStatus.CONFIRMED, "✅ Подтвердить"),
    (AppointmentStatus.CANCELLED, "🚫 Отменить запись"),
    (AppointmentStatus.COMPLETED, "✔️ Завершена"),
    (AppointmentStatus.NO_SHOW, "🙅 Неявка"),
]


def appointment_browser_back_to_search_kb() -> InlineKeyboardMarkup:
    """Единственная кнопка "к меню поиска" - для экранов ввода (ФИО/телефон)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ К меню поиска", callback_data="browse_appointments")
    return builder.as_markup()


def appointment_browser_cancel_edit_kb(appointment_id: int, mode: str, page: int) -> InlineKeyboardMarkup:
    """Единственная кнопка "отменить" - возврат к карточке записи без изменений."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="❌ Отменить",
        callback_data=ApptActionCB(
            action="cancel_edit", appointment_id=appointment_id, mode=mode, page=page,
        ).pack(),
    )
    return builder.as_markup()


def appointment_browser_search_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text="👤 Поиск по имени", callback_data="appt_search_name")
    builder.button(text="📞 Поиск по номеру", callback_data="appt_search_phone")
    builder.button(text="📋 Показать все записи", callback_data="appt_search_all")
    builder.button(text="⬅️ К меню", callback_data="back_to_main_records")

    builder.adjust(2, 1, 1)
    return builder.as_markup()


def appointment_browser_confirm_name_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Подтвердить", callback_data="appt_approve_search")
    builder.button(text="📝 Изменить ФИО", callback_data="appt_edit_search_name")
    builder.button(text="⬅️ К меню поиска", callback_data="browse_appointments")

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def appointment_browser_confirm_phone_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Подтвердить", callback_data="appt_approve_search")
    builder.button(text="📲 Изменить номер", callback_data="appt_edit_search_phone")
    builder.button(text="⬅️ К меню поиска", callback_data="browse_appointments")

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def appointment_list_kb(
    items: list[Appointment],
    mode: str,
    current_page: int,
    total_pages: int,
    tab: str = "",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for appointment in items:
        builder.button(
            text=build_appointment_button_text(appointment),
            callback_data=ApptCardCB(
                appointment_id=appointment.id, mode=mode, page=current_page, tab=tab,
            ).pack(),
        )

    rows = [1] * len(items)

    for tab_value in _TAB_ORDER:
        label = _TAB_LABELS[tab_value]
        text = f"• {label}" if tab_value == tab else label
        builder.button(text=text, callback_data=ApptPageCB(mode=mode, page=1, tab=tab_value).pack())
    rows += [3, 3]

    if total_pages > 1:
        prev_page = get_circular_page(current_page, total_pages, "prev")
        next_page = get_circular_page(current_page, total_pages, "next")

        builder.button(text=f"{current_page} из {total_pages}", callback_data="noop")
        builder.button(
            text="⬅️",
            callback_data=ApptPageCB(mode=mode, page=prev_page, tab=tab).pack(),
        )
        builder.button(
            text="➡️",
            callback_data=ApptPageCB(mode=mode, page=next_page, tab=tab).pack(),
        )
        rows += [1, 2]
    else:
        builder.button(text="Страница 1 из 1", callback_data="noop")
        rows += [1]

    builder.button(text="⬅️ К меню поиска", callback_data="browse_appointments")
    rows += [1]

    builder.adjust(*rows)
    return builder.as_markup()


def appointment_card_kb(
    appointment_id: int, mode: str, page: int, status: AppointmentStatus, tab: str = "",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    status_buttons_added = 0
    for button_status, text in _STATUS_ACTION_BUTTONS:
        if button_status == status:
            continue

        builder.button(
            text=text,
            callback_data=ApptActionCB(
                action="set_status", appointment_id=appointment_id, mode=mode, page=page,
                value=button_status.value,
            ).pack(),
        )
        status_buttons_added += 1

    builder.button(
        text="🕐 Изменить время",
        callback_data=ApptActionCB(action="edit_datetime", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text="📝 Изменить услугу",
        callback_data=ApptActionCB(action="edit_purpose", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text="🗑 Удалить",
        callback_data=ApptActionCB(action="delete", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text="⬅️ Назад к списку",
        callback_data=ApptPageCB(mode=mode, page=page, tab=tab).pack(),
    )

    status_rows = (2, 2) if status_buttons_added == 4 else (2, 1)
    builder.adjust(*status_rows, 2, 1, 1)
    return builder.as_markup()


def appointment_delete_confirm_kb(appointment_id: int, mode: str, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Да, удалить",
        callback_data=ApptActionCB(action="confirm_delete", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text="❌ Отмена",
        callback_data=ApptActionCB(action="cancel_delete", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )

    builder.adjust(1, 1)
    return builder.as_markup()


def appointment_delete_notify_kb(appointment_id: int, mode: str, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Да, уведомить",
        callback_data=ApptActionCB(
            action="confirm_delete_notify", appointment_id=appointment_id, mode=mode, page=page,
        ).pack(),
    )
    builder.button(
        text="🔕 Нет, без уведомления",
        callback_data=ApptActionCB(
            action="confirm_delete_silent", appointment_id=appointment_id, mode=mode, page=page,
        ).pack(),
    )

    builder.adjust(1, 1)
    return builder.as_markup()


def appointment_confirm_new_datetime_kb(appointment_id: int, mode: str, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить",
        callback_data=ApptActionCB(action="approve_new_datetime", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text="🔄 Ввести заново",
        callback_data=ApptActionCB(action="retry_new_datetime", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text="❌ Отменить",
        callback_data=ApptActionCB(action="cancel_edit", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def appointment_confirm_new_purpose_kb(appointment_id: int, mode: str, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить",
        callback_data=ApptActionCB(action="approve_new_purpose", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text="📝 Ввести заново",
        callback_data=ApptActionCB(action="retry_new_purpose", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text="❌ Отменить",
        callback_data=ApptActionCB(action="cancel_edit", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()
