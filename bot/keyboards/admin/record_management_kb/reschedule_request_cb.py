from aiogram.filters.callback_data import CallbackData


class RescheduleRequestActionCB(CallbackData, prefix="resch_req_act"):
    """Действие админа над заявкой клиента на перенос записи: accept, reject."""
    action: str
    appointment_id: int
