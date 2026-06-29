from bot.exceptions.exceptions import BotException


class UserAlreadyExistsError(BotException):
    """Пользователь уже зарегистрирован."""
    pass


class UserNotFoundError(BotException):
    """Пользователь не найден."""
    pass


class PhoneAlreadyExistsError(BotException):
    """Телефон уже используется."""
    pass


class InvalidFullNameError(BotException):
    """Некорректное ФИО."""
    pass


class InvalidPhoneError(BotException):
    """Некорректный номер телефона."""
    pass
