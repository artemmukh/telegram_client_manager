import re
from datetime import datetime

from bot.exceptions.appointment_exceptions import InvalidDatetimeError, InvalidPurposeError
from bot.exceptions.user_exceptions import InvalidFullNameError, InvalidPhoneError, PhoneAlreadyExistsError, ValidationError
from bot.repositories.user_repository import UserRepository
from bot.utils.tools import normalize_phone

DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

FULL_NAME_PATTERN = re.compile(
    r"^[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?"
    r"(?: [А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?){1,2}$"
)

PHONE_PATTERN = re.compile(r"^(?:\+998|998)?\d{9}$")

SEARCH_NAME_PATTERN = re.compile(
    r"^[А-ЯЁа-яё]{2,}(?:[- ][А-ЯЁа-яё]{2,})*$"
)



def validate_full_name(full_name: str, pattern) -> str:
    if not pattern.fullmatch(full_name.strip()):
        raise InvalidFullNameError(
            "Введите ФИО корректно.\n\n"
            "Например:\n"
            "Иван, Иван Иванов, Иван Иванов Иванович."
        )
    return full_name




def validate_phone(phone: str) -> str:
    phone = normalize_phone(phone)

    if not PHONE_PATTERN.fullmatch(phone):
        raise InvalidPhoneError(
            "Введите номер корректно.\n"
            "Форматы:\n"
            "901234567\n"
            "998901234567\n"
            "+998901234567"
        )

    return phone

async def validate_phone_available(
    user_repo: UserRepository,
    phone: str
):
    if await user_repo.phone_exists(phone):
        raise PhoneAlreadyExistsError(
            "Номер уже зарегистрирован. Пожалуйста, введите другой:"
        )

def validate_fields_filled(data):
    if "full_name" not in data:
        raise ValidationError("ФИО отсутствует.")

    if "phone" not in data:
        raise ValidationError("Телефон отсутствует.")


def validate_datetime(value: str) -> str:
    value = value.strip()

    if not DATETIME_PATTERN.fullmatch(value):
        raise InvalidDatetimeError(
            "Введите дату и время в формате ГГГГ-ММ-ДД ЧЧ:ММ.\n"
            "Например: 2026-07-10 14:30"
        )

    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        raise InvalidDatetimeError("Такой даты или времени не существует. Проверьте ввод.")

    return value


def validate_datetime_natural(value: str) -> str:
    """Validate datetime from natural Russian text or strict format."""
    from bot.services.utils.date_parser import parse_ru_datetime, format_datetime_for_db

    value = value.strip()

    if not value:
        raise InvalidDatetimeError(
            "Введите дату и время.\n"
            "Например: завтра в 3 часа, 13 сентября 15:30"
        )

    parsed_dt = parse_ru_datetime(value)

    if parsed_dt is None:
        raise InvalidDatetimeError(
            "Не смог распознать дату и время.\n"
            "Попробуйте снова:\n"
            "• завтра в 3 часа\n"
            "• 13 сентября 15:30\n"
            "• в понедельник в 14:00"
        )

    return format_datetime_for_db(parsed_dt)


def validate_purpose(value: str) -> str:
    value = value.strip()

    if not 2 <= len(value) <= 100:
        raise InvalidPurposeError(
            "Опишите услугу (от 2 до 100 символов).\n"
            "Например: Консультация, Чистка."
        )

    return value




