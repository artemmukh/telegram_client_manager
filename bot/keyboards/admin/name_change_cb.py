from aiogram.filters.callback_data import CallbackData


class NameChangeApprovalCB(CallbackData, prefix="name_change"):
    """Действие администратора по запросу смены ФИ: approve/reject."""
    action: str
    user_id: int
