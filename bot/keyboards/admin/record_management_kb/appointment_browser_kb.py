from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.utils.admin_utils.appointment_browser_helpers import build_appointment_button_text
from bot.handlers.utils.admin_utils.appointment_calendar_helpers import (
    CALENDAR_BACK_TO_SEARCH_LABEL,
    WEEKDAY_LABELS,
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
from bot.utils.appointment_enums import APPOINTMENT_TAB_ORDER, AppointmentStatus, tab_label
from bot.utils.pagination import get_circular_page

_TAB_ORDER = [status.value for status in APPOINTMENT_TAB_ORDER]

_STATUS_BUTTON_LABELS = {
    AppointmentStatus.CONFIRMED: {"ru": "✅ Подтвердить", "uz": "✅ Tasdiqlash"},
    AppointmentStatus.CANCELLED: {"ru": "🚫 Отменить запись", "uz": "🚫 Yozuvni bekor qilish"},
    AppointmentStatus.COMPLETED: {"ru": "✔️ Завершена", "uz": "✔️ Tugallangan"},
    AppointmentStatus.NO_SHOW: {"ru": "🙅 Неявка", "uz": "🙅 Kelmadi"},
}


def _status_button_text(status: AppointmentStatus, lang: str) -> str:
    labels = _STATUS_BUTTON_LABELS[status]
    return labels.get(lang, labels["ru"])


def _status_action_buttons(lang: str) -> list[tuple[AppointmentStatus, str]]:
    statuses = [
        AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW,
    ]
    return [(status, _status_button_text(status, lang)) for status in statuses]


def _pending_action_buttons(lang: str) -> list[tuple[AppointmentStatus, str]]:
    statuses = [AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED]
    return [(status, _status_button_text(status, lang)) for status in statuses]


def _post_appt_status_buttons(lang: str) -> list[tuple[AppointmentStatus, str]]:
    statuses = [AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW, AppointmentStatus.COMPLETED]
    return [(status, _status_button_text(status, lang)) for status in statuses]


def _status_change_menu_buttons(lang: str) -> list[tuple[AppointmentStatus, str]]:
    statuses = [AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW, AppointmentStatus.COMPLETED]
    return [(status, _status_button_text(status, lang)) for status in statuses]


_EDIT_PURPOSE_LABEL = {"ru": "📝 Изменить услугу", "uz": "📝 Xizmatni o'zgartirish"}
_PRICE_LABEL = {"ru": "💰 Цена", "uz": "💰 Narx"}
_FINISH_APPOINTMENT_LABEL = {"ru": "✅ Завершить приём", "uz": "✅ Qabulni yakunlash"}
_EDIT_TIME_LABEL = {"ru": "🕐 Изменить время", "uz": "🕐 Vaqtni o'zgartirish"}
_DELETE_LABEL = {"ru": "🗑 Удалить", "uz": "🗑 O'chirish"}
_CHANGE_STATUS_LABEL = {"ru": "🔁 Изменить статус", "uz": "🔁 Holatni o'zgartirish"}
_GET_MEDICAL_RECORD_LABEL = {"ru": "📄 Получить историю болезни", "uz": "📄 Kasallik tarixini olish"}
_ADD_MEDICAL_RECORD_LABEL = {"ru": "➕ Добавить документ", "uz": "➕ Hujjat qo'shish"}
_BACK_TO_LIST_LABEL = {"ru": "⬅️ Назад к списку", "uz": "⬅️ Ro'yxatga qaytish"}

_CANCEL_EDIT_LABEL = {"ru": "❌ Отменить", "uz": "❌ Bekor qilish"}
_SEARCH_BY_NAME_LABEL = {"ru": "👤 Поиск по имени", "uz": "👤 Ism bo'yicha qidirish"}
_SEARCH_BY_PHONE_LABEL = {"ru": "📞 Поиск по номеру", "uz": "📞 Raqam bo'yicha qidirish"}
_SHOW_ALL_LABEL = {"ru": "📋 Показать все записи", "uz": "📋 Barcha yozuvlarni ko'rsatish"}
_CALENDAR_LABEL = {"ru": "📅 Календарь", "uz": "📅 Kalendar"}
_BACK_TO_MENU_LABEL = {"ru": "⬅️ К меню", "uz": "⬅️ Menyuga"}
_CONFIRM_LABEL = {"ru": "✅ Подтвердить", "uz": "✅ Tasdiqlash"}
_EDIT_NAME_LABEL = {"ru": "📝 Изменить ФИ", "uz": "📝 F.I.Sh.ni o'zgartirish"}
_EDIT_PHONE_LABEL = {"ru": "📲 Изменить номер", "uz": "📲 Raqamni o'zgartirish"}
_ALL_DOCTORS_LABEL = {"ru": "👥 Все врачи", "uz": "👥 Barcha shifokorlar"}
_PAGE_INDICATOR_LABEL = {"ru": "{current} из {total}", "uz": "{current}/{total}-sahifa"}
_SINGLE_PAGE_LABEL = {"ru": "Страница 1 из 1", "uz": "1/1-sahifa"}
_BACK_LABEL = {"ru": "⬅️ Назад", "uz": "⬅️ Orqaga"}
_DELETE_CONFIRM_YES_LABEL = {"ru": "✅ Да, удалить", "uz": "✅ Ha, o'chirish"}
_DELETE_CONFIRM_NO_LABEL = {"ru": "❌ Отмена", "uz": "❌ Bekor qilish"}
_DELETE_NOTIFY_YES_LABEL = {"ru": "✅ Да, уведомить", "uz": "✅ Ha, xabar berish"}
_DELETE_NOTIFY_NO_LABEL = {"ru": "🔕 Нет, без уведомления", "uz": "🔕 Yo'q, xabarsiz"}
_RETRY_DATETIME_LABEL = {"ru": "🔄 Ввести заново", "uz": "🔄 Qayta kiritish"}
_RETRY_PURPOSE_LABEL = {"ru": "📝 Ввести заново", "uz": "📝 Qayta kiritish"}
_RETRY_PRICE_LABEL = {"ru": "💰 Ввести заново", "uz": "💰 Qayta kiritish"}

_STATUS_EDITABLE_STATUSES = {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED}
_SERVICE_EDITABLE_STATUSES = {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED}
_PRICE_EDITABLE_STATUSES = {AppointmentStatus.COMPLETED}
_TIME_EDITABLE_STATUSES = {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED}
_STATUS_CHANGE_MENU_STATUSES = {AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW, AppointmentStatus.CANCELLED}


def appointment_browser_back_to_search_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    """Единственная кнопка "к меню поиска" - для экранов ввода (ФИ/телефон)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=CALENDAR_BACK_TO_SEARCH_LABEL.get(lang, CALENDAR_BACK_TO_SEARCH_LABEL["ru"]),
        callback_data="browse_appointments",
    )
    return builder.as_markup()


def appointment_browser_cancel_edit_kb(
    appointment_id: int, mode: str, page: int, post_appt: bool = False, lang: str = "ru",
) -> InlineKeyboardMarkup:
    """Единственная кнопка "отменить" - возврат к карточке записи без изменений."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_CANCEL_EDIT_LABEL.get(lang, _CANCEL_EDIT_LABEL["ru"]),
        callback_data=ApptActionCB(
            action="cancel_edit", appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
        ).pack(),
    )
    return builder.as_markup()


def appointment_browser_search_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text=_SEARCH_BY_NAME_LABEL.get(lang, _SEARCH_BY_NAME_LABEL["ru"]), callback_data="appt_search_name")
    builder.button(text=_SEARCH_BY_PHONE_LABEL.get(lang, _SEARCH_BY_PHONE_LABEL["ru"]), callback_data="appt_search_phone")
    builder.button(text=_SHOW_ALL_LABEL.get(lang, _SHOW_ALL_LABEL["ru"]), callback_data="appt_search_all")
    builder.button(text=_CALENDAR_LABEL.get(lang, _CALENDAR_LABEL["ru"]), callback_data="appt_search_calendar")
    builder.button(text=_BACK_TO_MENU_LABEL.get(lang, _BACK_TO_MENU_LABEL["ru"]), callback_data="back_to_main_records")

    builder.adjust(2, 2, 1)
    return builder.as_markup()


def appointment_browser_confirm_name_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text=_CONFIRM_LABEL.get(lang, _CONFIRM_LABEL["ru"]), callback_data="appt_approve_search")
    builder.button(text=_EDIT_NAME_LABEL.get(lang, _EDIT_NAME_LABEL["ru"]), callback_data="appt_edit_search_name")
    builder.button(
        text=CALENDAR_BACK_TO_SEARCH_LABEL.get(lang, CALENDAR_BACK_TO_SEARCH_LABEL["ru"]),
        callback_data="browse_appointments",
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def appointment_browser_confirm_phone_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text=_CONFIRM_LABEL.get(lang, _CONFIRM_LABEL["ru"]), callback_data="appt_approve_search")
    builder.button(text=_EDIT_PHONE_LABEL.get(lang, _EDIT_PHONE_LABEL["ru"]), callback_data="appt_edit_search_phone")
    builder.button(
        text=CALENDAR_BACK_TO_SEARCH_LABEL.get(lang, CALENDAR_BACK_TO_SEARCH_LABEL["ru"]),
        callback_data="browse_appointments",
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def appointment_doctor_filter_kb(
    doctors: list[User], *, back_callback_data: str = "browse_appointments", back_label: str = "⬅️ К меню поиска",
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for doctor in doctors:
        builder.button(text=doctor.full_name, callback_data=ApptDoctorFilterCB(doctor_id=doctor.ID).pack())
    builder.button(text=_ALL_DOCTORS_LABEL.get(lang, _ALL_DOCTORS_LABEL["ru"]), callback_data=ApptDoctorFilterCB(doctor_id=0).pack())
    builder.button(text=back_label, callback_data=back_callback_data)

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
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for appointment in items:
        builder.button(
            text=build_appointment_button_text(appointment, lang),
            callback_data=ApptCardCB(
                appointment_id=appointment.id, mode=mode, page=current_page, tab=tab,
            ).pack(),
        )

    rows = [1] * len(items)

    for tab_value in _TAB_ORDER:
        label = tab_label(AppointmentStatus(tab_value), lang)
        text = f"• {label}" if tab_value == tab else label
        builder.button(text=text, callback_data=ApptPageCB(mode=mode, page=1, tab=tab_value).pack())
    rows += [3, 3]

    if total_pages > 1:
        prev_page = get_circular_page(current_page, total_pages, "prev")
        next_page = get_circular_page(current_page, total_pages, "next")

        page_text = _PAGE_INDICATOR_LABEL.get(lang, _PAGE_INDICATOR_LABEL["ru"]).format(
            current=current_page, total=total_pages,
        )
        builder.button(text=page_text, callback_data="noop")
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
        builder.button(text=_SINGLE_PAGE_LABEL.get(lang, _SINGLE_PAGE_LABEL["ru"]), callback_data="noop")
        rows += [1]

    builder.button(text=back_label, callback_data=back_callback_data)
    rows += [1]

    builder.adjust(*rows)
    return builder.as_markup()


def appointment_calendar_kb(
    year: int, month: int, *, back_callback_data: str = "browse_appointments", back_label: str = "⬅️ К меню поиска",
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    rows = []

    for label in WEEKDAY_LABELS.get(lang, WEEKDAY_LABELS_RU):
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

    builder.button(text=format_month_label(year, month, lang), callback_data="noop")
    rows.append(1)

    prev_year, prev_month = shift_month(year, month, "prev")
    next_year, next_month = shift_month(year, month, "next")

    builder.button(text="⬅️", callback_data=ApptCalendarMonthCB(year=prev_year, month=prev_month).pack())
    builder.button(text="➡️", callback_data=ApptCalendarMonthCB(year=next_year, month=next_month).pack())
    rows.append(2)

    builder.button(text=back_label, callback_data=back_callback_data)
    rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()


def appointment_card_kb(
    appointment_id: int, mode: str, page: int, status: AppointmentStatus, tab: str = "",
    post_appt: bool = False, selected_status: AppointmentStatus | None = None, lang: str = "ru",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    rows = []

    if post_appt:
        effective_selected = selected_status or status

        for button_status, text in _post_appt_status_buttons(lang):
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
            text=_EDIT_PURPOSE_LABEL.get(lang, _EDIT_PURPOSE_LABEL["ru"]),
            callback_data=ApptActionCB(
                action="edit_purpose", appointment_id=appointment_id, mode=mode, page=page, post_appt=True,
            ).pack(),
        )
        builder.button(
            text=_PRICE_LABEL.get(lang, _PRICE_LABEL["ru"]),
            callback_data=ApptActionCB(
                action="edit_price", appointment_id=appointment_id, mode=mode, page=page, post_appt=True,
            ).pack(),
        )
        rows.append(2)

        builder.button(
            text=_FINISH_APPOINTMENT_LABEL.get(lang, _FINISH_APPOINTMENT_LABEL["ru"]),
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
        action_buttons = (
            _pending_action_buttons(lang) if status == AppointmentStatus.PENDING else _status_action_buttons(lang)
        )

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
            text=_EDIT_TIME_LABEL.get(lang, _EDIT_TIME_LABEL["ru"]),
            callback_data=ApptActionCB(action="edit_datetime", appointment_id=appointment_id, mode=mode, page=page).pack(),
        )
        editing_buttons_added += 1
    if status in _SERVICE_EDITABLE_STATUSES:
        builder.button(
            text=_EDIT_PURPOSE_LABEL.get(lang, _EDIT_PURPOSE_LABEL["ru"]),
            callback_data=ApptActionCB(action="edit_purpose", appointment_id=appointment_id, mode=mode, page=page).pack(),
        )
        editing_buttons_added += 1
    if status in _PRICE_EDITABLE_STATUSES:
        builder.button(
            text=_PRICE_LABEL.get(lang, _PRICE_LABEL["ru"]),
            callback_data=ApptActionCB(action="edit_price", appointment_id=appointment_id, mode=mode, page=page).pack(),
        )
        editing_buttons_added += 1

    if editing_buttons_added:
        rows.append(editing_buttons_added)

    if status in _STATUS_EDITABLE_STATUSES:
        builder.button(
            text=_DELETE_LABEL.get(lang, _DELETE_LABEL["ru"]),
            callback_data=ApptActionCB(action="delete", appointment_id=appointment_id, mode=mode, page=page).pack(),
        )
        rows.append(1)

    if status in _STATUS_CHANGE_MENU_STATUSES:
        builder.button(
            text=_CHANGE_STATUS_LABEL.get(lang, _CHANGE_STATUS_LABEL["ru"]),
            callback_data=ApptActionCB(action="status_menu", appointment_id=appointment_id, mode=mode, page=page).pack(),
        )
        rows.append(1)

    if status == AppointmentStatus.COMPLETED:
        builder.button(
            text=_GET_MEDICAL_RECORD_LABEL.get(lang, _GET_MEDICAL_RECORD_LABEL["ru"]),
            callback_data=ApptActionCB(
                action="get_medical_record", appointment_id=appointment_id, mode=mode, page=page,
            ).pack(),
        )
        rows.append(1)

        builder.button(
            text=_ADD_MEDICAL_RECORD_LABEL.get(lang, _ADD_MEDICAL_RECORD_LABEL["ru"]),
            callback_data=ApptActionCB(
                action="add_medical_record", appointment_id=appointment_id, mode=mode, page=page,
            ).pack(),
        )
        rows.append(1)

    builder.button(
        text=_BACK_TO_LIST_LABEL.get(lang, _BACK_TO_LIST_LABEL["ru"]),
        callback_data=ApptPageCB(mode=mode, page=page, tab=tab).pack(),
    )
    rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()


def appointment_status_menu_kb(
    appointment_id: int, mode: str, page: int, tab: str, status: AppointmentStatus, lang: str = "ru",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    rows = []

    for button_status, text in _status_change_menu_buttons(lang):
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
        text=_BACK_LABEL.get(lang, _BACK_LABEL["ru"]),
        callback_data=ApptCardCB(appointment_id=appointment_id, mode=mode, page=page, tab=tab).pack(),
    )
    rows.append(1)

    builder.adjust(*rows)
    return builder.as_markup()


def appointment_delete_confirm_kb(appointment_id: int, mode: str, page: int, lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_DELETE_CONFIRM_YES_LABEL.get(lang, _DELETE_CONFIRM_YES_LABEL["ru"]),
        callback_data=ApptActionCB(action="confirm_delete", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text=_DELETE_CONFIRM_NO_LABEL.get(lang, _DELETE_CONFIRM_NO_LABEL["ru"]),
        callback_data=ApptActionCB(action="cancel_delete", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )

    builder.adjust(1, 1)
    return builder.as_markup()


def appointment_delete_notify_kb(appointment_id: int, mode: str, page: int, lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_DELETE_NOTIFY_YES_LABEL.get(lang, _DELETE_NOTIFY_YES_LABEL["ru"]),
        callback_data=ApptActionCB(
            action="confirm_delete_notify", appointment_id=appointment_id, mode=mode, page=page,
        ).pack(),
    )
    builder.button(
        text=_DELETE_NOTIFY_NO_LABEL.get(lang, _DELETE_NOTIFY_NO_LABEL["ru"]),
        callback_data=ApptActionCB(
            action="confirm_delete_silent", appointment_id=appointment_id, mode=mode, page=page,
        ).pack(),
    )

    builder.adjust(1, 1)
    return builder.as_markup()


def appointment_confirm_new_datetime_kb(appointment_id: int, mode: str, page: int, lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_CONFIRM_LABEL.get(lang, _CONFIRM_LABEL["ru"]),
        callback_data=ApptActionCB(action="approve_new_datetime", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text=_RETRY_DATETIME_LABEL.get(lang, _RETRY_DATETIME_LABEL["ru"]),
        callback_data=ApptActionCB(action="retry_new_datetime", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text=_CANCEL_EDIT_LABEL.get(lang, _CANCEL_EDIT_LABEL["ru"]),
        callback_data=ApptActionCB(action="cancel_edit", appointment_id=appointment_id, mode=mode, page=page).pack(),
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def appointment_confirm_new_purpose_kb(
    appointment_id: int, mode: str, page: int, post_appt: bool = False, lang: str = "ru",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_CONFIRM_LABEL.get(lang, _CONFIRM_LABEL["ru"]),
        callback_data=ApptActionCB(
            action="approve_new_purpose", appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
        ).pack(),
    )
    builder.button(
        text=_RETRY_PURPOSE_LABEL.get(lang, _RETRY_PURPOSE_LABEL["ru"]),
        callback_data=ApptActionCB(
            action="retry_new_purpose", appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
        ).pack(),
    )
    builder.button(
        text=_CANCEL_EDIT_LABEL.get(lang, _CANCEL_EDIT_LABEL["ru"]),
        callback_data=ApptActionCB(
            action="cancel_edit", appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
        ).pack(),
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def appointment_confirm_new_price_kb(
    appointment_id: int, mode: str, page: int, post_appt: bool = False, lang: str = "ru",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text=_CONFIRM_LABEL.get(lang, _CONFIRM_LABEL["ru"]),
        callback_data=ApptActionCB(
            action="approve_new_price", appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
        ).pack(),
    )
    builder.button(
        text=_RETRY_PRICE_LABEL.get(lang, _RETRY_PRICE_LABEL["ru"]),
        callback_data=ApptActionCB(
            action="retry_new_price", appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
        ).pack(),
    )
    builder.button(
        text=_CANCEL_EDIT_LABEL.get(lang, _CANCEL_EDIT_LABEL["ru"]),
        callback_data=ApptActionCB(
            action="cancel_edit", appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
        ).pack(),
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()
