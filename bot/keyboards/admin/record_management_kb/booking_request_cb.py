from aiogram.filters.callback_data import CallbackData


class BookingRequestActionCB(CallbackData, prefix="bkreq_act"):
    """Действие админа над заявкой на самозапись: confirm, propose, reject."""
    action: str
    appointment_id: int
