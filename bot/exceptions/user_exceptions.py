from bot.exceptions.exceptions import BotException

class ValidationError(BotException):
    """Некорректный ввод."""
    pass

class RoleError(BotException):
    pass

class UserAlreadyExistsError(ValidationError):
    """Пользователь уже зарегистрирован."""
    pass


class UserNotFoundError(ValidationError):
    """Пользователь не найден."""
    pass



PHONE_ALREADY_EXISTS_MESSAGE = {
    "ru": "Номер уже зарегистрирован. Пожалуйста, введите другой:",
    "uz": "Raqam allaqachon ro'yxatdan o'tgan. Iltimos, boshqasini kiriting:",
}


class PhoneAlreadyExistsError(ValidationError):
    """Телефон уже используется."""
    pass


class ContactOwnershipMismatchError(ValidationError):
    """Контакт принадлежит другому пользователю Telegram."""
    pass


class SamePhoneError(ValidationError):
    """Введен тот же телефон."""
    pass


class InvalidFullNameError(ValidationError):
    """Некорректное ФИ."""
    pass


class InvalidPhoneError(ValidationError):
    """Некорректный номер телефона."""
    pass


class InvalidBirthDateError(ValidationError):
    """Некорректная дата рождения."""
    pass



