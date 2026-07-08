from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError


class AppointmentNotFoundError(ValidationError):
    """Запись не найдена."""
    pass


class InvalidDatetimeError(ValidationError):
    """Некорректная дата или время."""
    pass


class InvalidPurposeError(ValidationError):
    """Некорректное описание услуги."""
    pass


class SchedulerError(BotException):
    """Ошибка планировщика (APScheduler)."""
    pass


class JobSchedulingError(SchedulerError):
    """Ошибка при планировании job'а."""
    pass


class JobCancellationError(SchedulerError):
    """Ошибка при отмене job'а."""
    pass


class NotificationDeliveryError(BotException):
    """Не удалось доставить уведомление в Telegram."""
    pass
