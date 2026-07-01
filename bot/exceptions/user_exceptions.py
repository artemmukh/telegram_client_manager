from bot.exceptions.exceptions import BotException

class ValidationError(BotException):
    """Некорректный ввод."""
    pass


class UserAlreadyExistsError(ValidationError):
    """Пользователь уже зарегистрирован."""
    pass


class UserNotFoundError(ValidationError):
    """Пользователь не найден."""
    pass


class PhoneAlreadyExistsError(ValidationError):
    """Телефон уже используется."""
    pass



class InvalidFullNameError(ValidationError):
    """Некорректное ФИО."""
    pass


class InvalidPhoneError(ValidationError):
    """Некорректный номер телефона."""
    pass



