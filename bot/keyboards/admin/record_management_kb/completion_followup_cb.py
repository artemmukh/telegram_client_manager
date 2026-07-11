from aiogram.filters.callback_data import CallbackData


class CompletionFollowupCB(CallbackData, prefix="appt_complete"):
    action: str  # "edit" | "skip"
    appointment_id: int
