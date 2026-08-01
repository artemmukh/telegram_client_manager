from aiogram.filters.callback_data import CallbackData


class AdminOccupiedSlotCB(CallbackData, prefix="adm_occ_slot"):
    """Открыть карточку записи, занимающей слот, в календаре создания записи.

    Только для чтения - выбирается первый занявший слот приём (см.
    AppointmentManagement.get_day_slot_occupancy: legacy-слоты mm с
    несколькими занявшими приёмами - редкий случай, не поддержанный в UI)."""
    appointment_id: int
