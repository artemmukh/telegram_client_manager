from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError


class AppointmentNotFoundError(ValidationError):
    """Запись не найдена."""
    pass


class AppointmentAlreadyFinalizedError(ValidationError):
    """Запись уже находится в финальном статусе и не может быть подтверждена."""
    pass


class AwaitingClinicDecisionError(ValidationError):
    """Заявка на самозапись ещё не рассмотрена клиникой."""
    pass


class CancellationWindowExpiredError(ValidationError):
    """Отмена записи менее чем за 2 часа до приёма."""
    pass


class InvalidDatetimeError(ValidationError):
    """Некорректная дата или время."""
    pass


class InvalidPurposeError(ValidationError):
    """Некорректное описание услуги."""
    pass


class NegotiationInProgressError(ValidationError):
    """Действие недоступно: по заявке уже есть предложенное время, ожидающее ответа клиента."""
    pass


class NoPendingProposalError(ValidationError):
    """Нет предложенного времени, ожидающего ответа."""
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
