from bot.exceptions.exceptions import BotException


class MedicalRecordGenerationError(BotException):
    """Не удалось сгенерировать текстовые поля истории болезни через LLM."""


class MedicalRecordDeletionError(BotException):
    """Не удалось безопасно удалить файл или запись истории болезни."""
