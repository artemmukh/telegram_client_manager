from aiogram.filters.callback_data import CallbackData


class ClientManagePageCB(CallbackData, prefix="cl_mng_page"):
    """Навигация по странице списка активных записей."""
    page: int


class ClientManageCardCB(CallbackData, prefix="cl_mng_card"):
    """Открыть карточку записи (page - куда вернуться)."""
    appointment_id: int
    page: int


class ClientManageActionCB(CallbackData, prefix="cl_mng_act"):
    """Действие над записью в карточке управления."""
    action: str
    appointment_id: int
    page: int
