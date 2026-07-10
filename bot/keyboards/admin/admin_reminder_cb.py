from aiogram.filters.callback_data import CallbackData


class AdminReminderPresetCB(CallbackData, prefix="adm_reminder"):
    preset: str
