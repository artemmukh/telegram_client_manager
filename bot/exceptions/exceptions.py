


class BotException(Exception):
    def __init__(self, message: str | dict[str, str] = ""):
        if isinstance(message, dict):
            localized = dict(message)
            message = localized.get("ru", "")
        else:
            localized = {"ru": message} if message else {}
        self._localized = localized
        super().__init__(message)

    def localized(self, lang: str = "ru") -> str:
        return self._localized.get(lang, self._localized.get("ru", str(self)))


class PaginationError(BotException):
    """Ошибка при постраничном выводе списка."""
    pass


