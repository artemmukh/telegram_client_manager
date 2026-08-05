from bot.exceptions.user_exceptions import ValidationError


class InvalidBlockRangeError(ValidationError):
    """Некорректный диапазон блокировки: конец раньше/равен началу либо начало в прошлом."""
    pass


class BlockedSlotNotFoundError(ValidationError):
    """Блокировка не найдена."""
    pass


class BlockedSlotAlreadyCancelledError(ValidationError):
    """Блокировка уже отменена."""
    pass
