from aiogram.filters.callback_data import CallbackData


class ApptPageCB(CallbackData, prefix="appt_page"):
    """Навигация по странице / переключение вкладки списка записей.

    tab - одна из 6 вкладок по статусу ('confirmed'/'pending'/'cancelled'/
    'no_show'/'completed'/'expired'), применяется для всех режимов
    (mode="list"/"search"/"phone").
    """
    mode: str
    page: int
    tab: str = ""


class ApptCardCB(CallbackData, prefix="appt_card"):
    """Открыть карточку записи / вернуться к списку (mode+page+tab - куда вернуться)."""
    appointment_id: int
    mode: str
    page: int
    tab: str = ""


class ApptActionCB(CallbackData, prefix="appt_act"):
    """Действие в карточке записи: set_status, edit_datetime, edit_purpose, delete,
    confirm_delete, cancel_delete, confirm_delete_notify, confirm_delete_silent."""
    action: str
    appointment_id: int
    mode: str
    page: int
    value: str = ""
