from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError


class AppointmentAlreadyExistsError(BotException):
    """Запись уже существует."""
    pass


class AppointmentNotFoundError(ValidationError):
    """Запись не найдена."""
    pass


class BusyTimeError(BotException):
    """Выбранное время занято."""
    pass


class InvalidDatetimeError(ValidationError):
    """Некорректная дата или время."""
    pass


class InvalidPurposeError(ValidationError):
    """Некорректное описание услуги."""
    pass
