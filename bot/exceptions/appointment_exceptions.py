from bot.exceptions.exceptions import BotException


class AppointmentAlreadyExistsError(BotException):
    """Запись уже существует."""
    pass


class AppointmentNotFoundError(BotException):
    """Запись не найдена."""
    pass


class BusyTimeError(BotException):
    """Выбранное время занято."""
    pass
