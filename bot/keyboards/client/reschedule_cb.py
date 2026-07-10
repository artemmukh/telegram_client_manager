from aiogram.filters.callback_data import CallbackData


class ClientRescheduleStartCB(CallbackData, prefix="cl_resch_start"):
    """Начать перенос существующей записи."""
    appointment_id: int


class ClientRescheduleDayPageCB(CallbackData, prefix="cl_resch_daypg"):
    """Переключение недели в выборе дня переноса."""
    appointment_id: int
    week_offset: int


class ClientRescheduleDayCB(CallbackData, prefix="cl_resch_day"):
    """Выбор конкретного дня переноса."""
    appointment_id: int
    week_offset: int
    day_iso: str


class ClientRescheduleSlotCB(CallbackData, prefix="cl_resch_slot", sep="|"):
    """Выбор времени переноса. Отдельный разделитель, т.к. slot содержит ':' (HH:MM)."""
    appointment_id: int
    slot: str


class ClientRescheduleCancelCB(CallbackData, prefix="cl_resch_cancel"):
    """Отмена мастера переноса - возврат к карточке записи."""
    appointment_id: int


class ClientRescheduleSubmitCB(CallbackData, prefix="cl_resch_submit"):
    """Подтверждение отправки заявки на перенос."""
    appointment_id: int
