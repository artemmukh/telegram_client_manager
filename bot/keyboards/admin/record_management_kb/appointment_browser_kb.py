from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.utils.admin_utils.appointment_browser_helpers import build_appointment_button_text
from bot.handlers.utils.admin_utils.appointment_calendar_helpers import (
    WEEKDAY_LABELS_RU,
    clamp_month_to_range,
    format_month_label,
    get_month_grid,
    shift_month,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import (
    ApptActionCB,
    ApptCalendarDayCB,
    ApptCalendarMonthCB,
    ApptCardCB,
    ApptDoctorFilterCB,
    ApptPageCB,
)
from bot.models.appointment import Appointment
from bot.models.user import User
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

_PENDING_ACTION_BUTTONS = [
    (AppointmentStatus.CONFIRMED, "✅ Подтвердить"),
    (AppointmentStatus.CANCELLED, "🚫 Отменить запись"),
]

_POST_APPT_STATUS_BUTTONS = [
    (AppointmentStatus.CANCELLED, "🚫 Отменить запись"),
    (AppointmentStatus.NO_SHOW, "🙅 Неявка"),
    (AppointmentStatus.COMPLETED, "✔️ Завершена"),
]

_STATUS_CHANGE_MENU_BUTTONS = [
    (AppointmentStatus.CANCELLED, "🚫 Отменить запись"),
    (AppointmentStatus.NO_SHOW, "🙅 Неявка"),
    (AppointmentStatus.COMPLETED, "✔️ Завершена"),
]

_STATUS_EDITABLE_STATUSES = {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED}
_SERVICE_EDITABLE_STATUSES = {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED}
_PRICE_EDITABLE_STATUSES = {AppointmentStatus.COMPLETED}
_TIME_EDITABLE_STATUSES = {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED}
_STATUS_CHANGE_MENU_STATUSES = {AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW, AppointmentStatus.CANCELLED}


def appointment_browser_back_to_search_kb() -> InlineKeyboardMarkup:
    """Единственная кнопка "к меню поиска" - для экранов ввода (ФИ/телефон)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ К меню поиска", callback_data="browse_appointments")
    return builder.as_markup()


def appointment_browser_cancel_edit_kb(
    appointment_id: int, mode: str, page: int, post_appt: bool = False,
) -> InlineKeyboardMarkup:
    """Единственная кнопка "отменить" - возврат к карточке записи без изменений."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="❌ Отменить",
        callback_data=ApptActionCB(
            action="cancel_edit", appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
        ).pack(),
    )
    return builder.as_markup()


def appointment_browser_search_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text="👤 Поиск по имени", callback_data="appt_search_name")
    builder.button(text="📞 Поиск по номеру", callback_data="appt_search_phone")
    builder.button(text="📋 Показать все записи", callback_data="appt_search_all")
    builder.button(text="📅 Календарь", callback_data="appt_search_calendar")
    builder.button(text="⬅️ К меню", callback_data="back_to_main_records")

    builder.adjust(2, 2, 1)
    return builder.as_markup()


def appointment_browser_confirm_name_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Подтвердить", callback_data="appt_approve_search")
    builder.button(text="📝 Изменить ФИ", callback_data="appt_edit_search_name")
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


def appointment_doctor_filter_kb(doctors: list[User]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for doctor in doctors:
        builder.button(text=doctor.full_name, callback_data=ApptDoctorFilterCB(doctor_id=doctor.ID).pack())
    builder.button(text="👥 Все врачи", callback_data=ApptDoctorFilterCB(doctor_id=0).pack())
    builder.button(text="⬅️ К меню поиска", callback_data="browse_appointments")

    builder.adjust(*([1] * len(doctors)), 1, 1)
    return builder.as_markup()


def appointment_list_kb(
    items: list[Appointment],
    mode: str,
    current_page: int,
    total_pages: int,
    tab: str = "",
    back_callback_data: str = "browse_appointments",
    back_label: str = "⬅️ К меню поиска",
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

    builder.button(text=back_label, callback_data=back_callback_data)
    rows += [1]

    builder.adjust(*rows)
    return builder.as_markup()


def appointment_calendar_kb(year: int, month: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    rows = []

    for label in WEEKDAY_LABELS_RU:
        builder.button(text=label, callback_data="noop")
    rows.append(7)

    grid = get_month_grid(year, month)
    for day, cell_year, cell_month in grid:
        in_range = clamp_month_to_range(cell_year, cell_month) == (cell_year, cell_month)
        callback_data = (
            ApptCalendarDayCB(year=cell_year, month=cell_month, day=day).pack() if in_range else "noop"
        )
        text = str(day) if cell_month == month else f"·{day}"
        builder.button(text=text, callback_data=callback_data)
    rows += [7] * (len(grid) // 7)

    builder.button(text=format_month_label(year, month), callback_data="noop")
    rows.append(1)

    prev_year, prev_month = shift_month(year, month, "prev")
    next_year, next_month = shift_month(year, month, "next")

    builder.button(text="⬅️", callback_data=ApptCalendarMonthCB(year=prev_year, month=prev_month).pack())
    builder.button(text="➡️", callback_data=ApptCalendarMonthCB(year=next_year, month=next_month).pack())
    rows.append(2)

    builder.button(text="⬅️ К меню поиска", callback_data="browse_appointments")
    rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()


def appointment_card_kb(
    appointment_id: int, mode: str, page: int, status: AppointmentStatus, tab: str = "",
    post_appt: bool = False, selected_status: AppointmentStatus | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    rows = []

    if post_appt:
        effective_selected = selected_status or status

        for button_status, text in _POST_APPT_STATUS_BUTTONS:
            label = f"☑️ {text}" if button_status == effective_selected else text
            builder.button(
                text=label,
                callback_data=ApptActionCB(
                    action="select_status", appointment_id=appointment_id, mode=mode, page=page,
                    value=button_status.value, post_appt=True,
                ).pack(),
            )
        rows.append(3)

        builder.button(
            text="📝 Изменить услугу",
            callback_data=ApptActionCB(
                action="edit_purpose", appointment_id=appointment_id, mode=mode, page=page, post_appt=True,
            ).pack(),
        )
        builder.button(
            text="💰 Цена",
            callback_data=ApptActionCB(
                action="edit_price", appointment_id=appointment_id, mode=mode, page=page, post_appt=True,
            ).pack(),
        )
        rows.append(2)

        builder.button(
            text="✅ Завершить приём",
            callback_data=ApptActionCB(
                action="finish_appointment", appointment_id=appointment_id, mode=mode, page=page, post_appt=True,
                value=effective_selected.value,
            ).pack(),
        )
        rows.append(1)

        builder.adjust(*rows)
        return builder.as_markup()

    status_buttons_added = 0
    if status in _STATUS_EDITABLE_STATUSES:
        action_buttons = _PENDING_ACTION_BUTTONS if status == AppointmentStatus.PENDING else _STATUS_ACTION_BUTTONS

        for button_status, text in action_buttons:
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

        rows += [2, 2] if status_buttons_added == 4 else [2] if status_buttons_added == 2 else [2, 1]

    editing_buttons_added = 0
    if status in _TIME_EDITABLE_STATUSES:
        builder.button(
            text="🕐 Изменить время",
            callback_data=ApptActionCB(action="edit_datetime", appointment_id=appointment_id, mode=mode, page=page).pack(),
        )
        editing_buttons_added += 1
    if status in _SERVICE_EDITABLE_STATUSES:
        builder.button(
            text="📝 Изменить услугу",
            callback_data=ApptActionCB(action="edit_purpose", appointment_id=appointment_id, mode=mode, page=page).pack(),
        )
        editing_buttons_added += 1
    if status in _PRICE_EDITABLE_STATUSES:
        builder.button(
            text="💰 Цена",
            callback_data=ApptActionCB(action="edit_price", appointment_id=appointment_id, mode=mode, page=page).pack(),
        )
        editing_buttons_added += 1

    if editing_buttons_added:
        rows.append(editing_buttons_added)

    if status in _STATUS_EDITABLE_STATUSES:
        builder.button(
            text="🗑 Удалить",
            callback_data=ApptActionCB(action="delete", appointment_id=appointment_id, mode=mode, page=page).pack(),
        )
        rows.append(1)

    if status in _STATUS_CHANGE_MENU_STATUSES:
        builder.button(
            text="🔁 Изменить статус",
            callback_data=ApptActionCB(action="status_menu", appointment_id=appointment_id, mode=mode, page=page).pack(),
        )
        rows.append(1)

    if status == AppointmentStatus.COMPLETED:
        builder.button(
            text="📄 Получить историю болезни",
            callback_data=ApptActionCB(
                action="get_medical_record", appointment_id=appointment_id, mode=mode, page=page,
            ).pack(),
        )
        rows.append(1)

        builder.button(
            text="➕ Добавить документ",
            callback_data=ApptActionCB(
                action="add_medical_record", appointment_id=appointment_id, mode=mode, page=page,
            ).pack(),
        )
        rows.append(1)

    builder.button(
        text="⬅️ Назад к списку",
        callback_data=ApptPageCB(mode=mode, page=page, tab=tab).pack(),
    )
    rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()


def appointment_status_menu_kb(
    appointment_id: int, mode: str, page: int, tab: str, status: AppointmentStatus,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    rows = []

    for button_status, text in _STATUS_CHANGE_MENU_BUTTONS:
        if button_status == status:
            continue

        builder.button(
            text=text,
            callback_data=ApptActionCB(
                action="set_status", appointment_id=appointment_id, mode=mode, page=page, value=button_status.value,
            ).pack(),
        )
    rows.append(2)

    builder.button(
        text="⬅️ Назад",
        callback_data=ApptCardCB(appointment_id=appointment_id, mode=mode, page=page, tab=tab).pack(),
    )
    rows.append(1)

    builder.adjust(*rows)
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


def appointment_confirm_new_purpose_kb(
    appointment_id: int, mode: str, page: int, post_appt: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить",
        callback_data=ApptActionCB(
            action="approve_new_purpose", appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
        ).pack(),
    )
    builder.button(
        text="📝 Ввести заново",
        callback_data=ApptActionCB(
            action="retry_new_purpose", appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
        ).pack(),
    )
    builder.button(
        text="❌ Отменить",
        callback_data=ApptActionCB(
            action="cancel_edit", appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
        ).pack(),
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def appointment_confirm_new_price_kb(
    appointment_id: int, mode: str, page: int, post_appt: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить",
        callback_data=ApptActionCB(
            action="approve_new_price", appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
        ).pack(),
    )
    builder.button(
        text="💰 Ввести заново",
        callback_data=ApptActionCB(
            action="retry_new_price", appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
        ).pack(),
    )
    builder.button(
        text="❌ Отменить",
        callback_data=ApptActionCB(
            action="cancel_edit", appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
        ).pack(),
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()
