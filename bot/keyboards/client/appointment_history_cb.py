from aiogram.filters.callback_data import CallbackData


class ClientHistoryPageCB(CallbackData, prefix="cl_hist_page"):
    """Навигация по странице / переключение вкладки истории записей."""
    tab: str
    page: int


class ClientHistoryCardCB(CallbackData, prefix="cl_hist_card"):
    """Открыть карточку записи / вернуться к списку (tab+page - куда вернуться)."""
    appointment_id: int
    tab: str
    page: int
