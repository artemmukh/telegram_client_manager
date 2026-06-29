from bot.exceptions.exceptions import BotException


class RecordAlreadyExistsError(BotException):
    """Запись уже существует."""
    pass


class RecordNotFoundError(BotException):
    """Запись не найдена."""
    pass


class BusyTimeError(BotException):
    """Выбранное время занято."""
    pass