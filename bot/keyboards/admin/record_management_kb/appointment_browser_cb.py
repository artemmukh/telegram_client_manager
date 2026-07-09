from aiogram.filters.callback_data import CallbackData


class ApptPageCB(CallbackData, prefix="appt_page"):
    """Навигация по странице списка записей."""
    mode: str
    page: int


class ApptCardCB(CallbackData, prefix="appt_card"):
    """Открыть карточку записи / вернуться к списку (mode+page - куда вернуться)."""
    appointment_id: int
    mode: str
    page: int


class ApptActionCB(CallbackData, prefix="appt_act"):
    """Действие в карточке записи: set_status, edit_datetime, edit_purpose, delete, confirm_delete, cancel_delete."""
    action: str
    appointment_id: int
    mode: str
    page: int
    value: str = ""
