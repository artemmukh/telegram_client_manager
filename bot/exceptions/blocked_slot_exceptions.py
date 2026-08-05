from bot.exceptions.user_exceptions import ValidationError


class InvalidBlockRangeError(ValidationError):
    """Некорректный диапазон блокировки: конец раньше/равен началу либо интервал полностью в прошлом."""
    pass


class InvalidBlockReasonError(ValidationError):
    """Некорректная причина блокировки."""
    pass


class BlockedSlotNotFoundError(ValidationError):
    """Блокировка не найдена."""
    pass


class BlockedSlotAlreadyCancelledError(ValidationError):
    """Блокировка уже отменена."""
    pass
