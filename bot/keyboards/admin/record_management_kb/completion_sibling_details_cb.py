from aiogram.filters.callback_data import CallbackData


class CompletionSiblingDetailsCB(CallbackData, prefix="completion_sibling_details"):
    appointment_id: int
    actor_user_id: int


class CompletionSiblingHideDetailsCB(CallbackData, prefix="completion_sibling_hide_details"):
    appointment_id: int
    actor_user_id: int
