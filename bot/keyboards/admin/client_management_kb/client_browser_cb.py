from aiogram.filters.callback_data import CallbackData


class ClientPageCB(CallbackData, prefix="cl_page"):
    """Навигация по странице списка клиентов."""
    mode: str
    page: int


class ClientCardCB(CallbackData, prefix="cl_card"):
    """Открыть карточку клиента / вернуться к списку (mode+page - куда вернуться)."""
    client_id: int
    mode: str
    page: int


class ClientActionCB(CallbackData, prefix="cl_act"):
    """Действие в карточке клиента: edit_name, edit_phone, delete, confirm_delete, cancel_delete."""
    action: str
    client_id: int
    mode: str
    page: int
