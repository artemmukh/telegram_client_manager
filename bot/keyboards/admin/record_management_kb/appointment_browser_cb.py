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
    """Открыть карточку записи / вернуться к списку (mode+page+tab - куда вернуться).

    post_appt - открыта ли карточка в режиме послеприёмного редактирования
    (отдельно от mode, который сохраняет семантику списка/поиска).
    """
    appointment_id: int
    mode: str
    page: int
    tab: str = ""
    post_appt: bool = False


class ApptActionCB(CallbackData, prefix="appt_act"):
    """Действие в карточке записи: set_status, edit_datetime, edit_purpose, edit_price,
    finish_appointment, delete, confirm_delete, cancel_delete, confirm_delete_notify,
    confirm_delete_silent, get_medical_record, add_medical_record.

    post_appt - выполняется ли действие в режиме послеприёмного редактирования
    (отдельно от mode, который сохраняет семантику списка/поиска).
    """
    action: str
    appointment_id: int
    mode: str
    page: int
    value: str = ""
    post_appt: bool = False


class ApptCalendarMonthCB(CallbackData, prefix="appt_cal_month"):
    """Переключение месяца в календарной сетке (кнопки '<'/'>')."""
    year: int
    month: int


class ApptCalendarDayCB(CallbackData, prefix="appt_cal_day"):
    """Выбор дня в календарной сетке."""
    year: int
    month: int
    day: int


class ApptDoctorFilterCB(CallbackData, prefix="appt_doc_filter"):
    """Выбор врача для фильтрации списка записей (0 = все врачи)."""
    doctor_id: int = 0


class ApptDoctorFilterEntryCB(CallbackData, prefix="appt_doc_reentry"):
    """Повторный вход в экран выбора врача из списка записей (mode="list"/"search"/"phone")."""
    mode: str
