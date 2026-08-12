from aiogram.filters.callback_data import CallbackData


class CompletionDetailsCB(CallbackData, prefix="completion_details"):
    appointment_id: int


class CompletionHideDetailsCB(CallbackData, prefix="completion_hide_details"):
    appointment_id: int
