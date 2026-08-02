from datetime import datetime

from bot.exceptions.user_exceptions import InvalidBirthDateError, ValidationError
from bot.services.utils.date_parser import get_current_tashkent_time
from bot.validators.validators import validate_birth_date

_BIRTH_DATE_IN_FUTURE_MESSAGE = {
    "ru": "Дата рождения не может быть в будущем.",
    "uz": "Tug'ilgan sana kelajakda bo'lishi mumkin emas.",
}

_BIRTH_DATE_INVALID_MESSAGE = {
    "ru": "Проверьте дату рождения.",
    "uz": "Tug'ilgan sanani tekshiring.",
}

_GENDER_INVALID_MESSAGE = {
    "ru": "Некорректное значение пола.",
    "uz": "Jins qiymati noto'g'ri.",
}


def validate_and_normalize_personal_data(
    birth_date: str | None, gender: str | None,
) -> tuple[str | None, str | None]:
    if birth_date is not None:
        birth_date = validate_birth_date(birth_date)

        now = datetime.strptime(get_current_tashkent_time(), "%Y-%m-%d %H:%M:%S")
        parsed_birth_date = datetime.strptime(birth_date, "%Y-%m-%d")

        if parsed_birth_date > now:
            raise InvalidBirthDateError(_BIRTH_DATE_IN_FUTURE_MESSAGE)

        age_years = (now - parsed_birth_date).days / 365.25
        if age_years > 120:
            raise InvalidBirthDateError(_BIRTH_DATE_INVALID_MESSAGE)

    if gender is not None and gender not in {"male", "female"}:
        raise ValidationError(_GENDER_INVALID_MESSAGE)

    return birth_date, gender
