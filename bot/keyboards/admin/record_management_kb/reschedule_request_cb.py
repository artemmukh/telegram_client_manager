from aiogram.filters.callback_data import CallbackData


class RescheduleRequestActionCB(CallbackData, prefix="resch_req_act"):
    """Действие админа над заявкой клиента на перенос записи: accept, reject,
    propose, cancel_propose, retry_propose_datetime, approve_propose_datetime."""
    action: str
    appointment_id: int
