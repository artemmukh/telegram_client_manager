from aiogram.filters.callback_data import CallbackData


class ClientReminderPresetCB(CallbackData, prefix="cl_reminder"):
    preset: str
