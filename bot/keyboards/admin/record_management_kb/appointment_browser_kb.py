from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.utils.admin_utils.appointment_browser_helpers import build_appointment_button_text
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import (
    ApptActionCB,
    ApptCardCB,
    ApptPageCB,
)
from bot.models.appointment import Appointment
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.pagination import get_circular_page


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
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for appointment in items:
        builder.button(
            text=build_appointment_button_text(appointment),
            callback_data=ApptCardCB(appointment_id=appointment.id, mode=mode, page=current_page).pack(),
        )

    rows = [1] * len(items)

    if total_pages > 1:
        prev_page = get_circular_page(current_page, total_pages, "prev")
        next_page = get_circular_page(current_page, total_pages, "next")

        builder.button(text=f"{current_page} из {total_pages}", callback_data="noop")
        builder.button(
            text="⬅️",
            callback_data=ApptPageCB(mode=mode, page=prev_page).pack(),
        )
        builder.button(
            text="➡️",
            callback_data=ApptPageCB(mode=mode, page=next_page).pack(),
        )
        rows += [1, 2]
    else:
        builder.button(text="Страница 1 из 1", callback_data="noop")
        rows += [1]

    builder.button(text="⬅️ К меню поиска", callback_data="browse_appointments")
    rows += [1]

    builder.adjust(*rows)
    return builder.as_markup()


def appointment_card_kb(appointment_id: int, mode: str, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить",
        callback_data=ApptActionCB(
            action="set_status", appointment_id=appointment_id, mode=mode, page=page,
            value=AppointmentStatus.CONFIRMED.value,
        ).pack(),
    )
    builder.button(
        text="🚫 Отменить запись",
        callback_data=ApptActionCB(
            action="set_status", appointment_id=appointment_id, mode=mode, page=page,
            value=AppointmentStatus.CANCELLED.value,
        ).pack(),
    )
    builder.button(
        text="✔️ Завершена",
        callback_data=ApptActionCB(
            action="set_status", appointment_id=appointment_id, mode=mode, page=page,
            value=AppointmentStatus.COMPLETED.value,
        ).pack(),
    )
    builder.button(
        text="🙅 Неявка",
        callback_data=ApptActionCB(
            action="set_status", appointment_id=appointment_id, mode=mode, page=page,
            value=AppointmentStatus.NO_SHOW.value,
        ).pack(),
    )
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
        callback_data=ApptPageCB(mode=mode, page=page).pack(),
    )

    builder.adjust(2, 2, 2, 1, 1)
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
