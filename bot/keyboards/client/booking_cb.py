from aiogram.filters.callback_data import CallbackData


class ClientBookDoctorCB(CallbackData, prefix="cl_book_doc"):
    """Выбор врача для самозаписи."""
    staff_user_id: int


class ClientBookDayPageCB(CallbackData, prefix="cl_book_daypg"):
    """Переключение недели в выборе дня."""
    week_offset: int


class ClientBookDayCB(CallbackData, prefix="cl_book_day"):
    """Выбор конкретного дня для записи."""
    week_offset: int
    day_iso: str


class ClientBookSlotCB(CallbackData, prefix="cl_book_slot", sep="|"):
    """Выбор времени записи. Отдельный разделитель, т.к. slot содержит ':' (HH:MM)."""
    slot: str
