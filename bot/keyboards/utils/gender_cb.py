from aiogram.filters.callback_data import CallbackData


class GenderCB(CallbackData, prefix="reg_gender"):
    """Выбор пола при регистрации клиента."""
    value: str
