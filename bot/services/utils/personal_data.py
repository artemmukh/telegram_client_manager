from datetime import datetime

from bot.exceptions.user_exceptions import InvalidBirthDateError, ValidationError
from bot.services.utils.date_parser import get_current_tashkent_time
from bot.validators.validators import validate_birth_date


def validate_and_normalize_personal_data(
    birth_date: str | None, gender: str | None,
) -> tuple[str | None, str | None]:
    if birth_date is not None:
        birth_date = validate_birth_date(birth_date)

        now = datetime.strptime(get_current_tashkent_time(), "%Y-%m-%d %H:%M:%S")
        parsed_birth_date = datetime.strptime(birth_date, "%Y-%m-%d")

        if parsed_birth_date > now:
            raise InvalidBirthDateError("Дата рождения не может быть в будущем.")

        age_years = (now - parsed_birth_date).days / 365.25
        if age_years > 120:
            raise InvalidBirthDateError("Проверьте дату рождения.")

    if gender is not None and gender not in {"male", "female"}:
        raise ValidationError("Некорректное значение пола.")

    return birth_date, gender
