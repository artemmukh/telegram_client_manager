from aiogram.filters.callback_data import CallbackData


class LanguageCB(CallbackData, prefix="reg_lang"):
    """Language selection for client registration and profile language switch."""
    value: str
