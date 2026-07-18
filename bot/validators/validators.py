import re
from datetime import datetime

from bot.exceptions.appointment_exceptions import InvalidDatetimeError, InvalidPriceError, InvalidPurposeError
from bot.exceptions.user_exceptions import InvalidFullNameError, InvalidPhoneError, ValidationError
from bot.utils.tools import normalize_phone

DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

FULL_NAME_PATTERN = re.compile(
    r"^[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?"
    r"(?: [А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?){1,2}$"
)

PHONE_PATTERN = re.compile(
    r"^(?:"
    r"\+998\d{9}|"    # Uzbekistan: +998 XXXXXXXXX (9 digits)
    r"\+7\d{10}|"     # Russia: +7 XXXXXXXXXX (10 digits)
    r"\+375\d{9}"     # Belarus: +375 XXXXXXXXX (9 digits)
    r")$"
)

SEARCH_NAME_PATTERN = re.compile(
    r"^[А-ЯЁа-яё]{2,}(?:[- ][А-ЯЁа-яё]{2,})*$"
)



def validate_full_name(full_name: str, pattern) -> str:
    if not pattern.fullmatch(full_name.strip()):
        raise InvalidFullNameError(
            "Введите ФИ корректно.\n\n"
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


def validate_fields_filled(data):
    if "full_name" not in data:
        raise ValidationError("ФИ отсутствует.")

    if "phone" not in data:
        raise ValidationError("Телефон отсутствует.")


def validate_datetime(value: str) -> str:
    value = value.strip()

    if not DATETIME_PATTERN.fullmatch(value):
        raise InvalidDatetimeError(
            "Ошибка формата даты и времени.\n\n"
            "Правильный формат: ГГГГ-ММ-ДД ЧЧ:ММ\n"
            "Пример: 2026-07-10 14:30\n"
            "Или: 24.07.26 12.30, 24.07.2026 12:30\n\n"
            "Или используйте русский текст:\n"
            "завтра в 3 часа, среда в 14:00, 13 сентября 15:30"
        )

    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        raise InvalidDatetimeError("Такой даты или времени не существует. Проверьте ввод.")

    return value


def validate_purpose(value: str) -> str:
    value = value.strip()

    if not 2 <= len(value) <= 100:
        raise InvalidPurposeError(
            "Опишите услугу (от 2 до 100 символов).\n"
            "Например: Консультация, Чистка."
        )

    return value


def validate_price(value: str) -> float:
    value = value.strip().replace(",", ".")

    try:
        price = float(value)
    except ValueError:
        raise InvalidPriceError(
            "Введите цену числом.\n"
            "Например: 150000, 99.90."
        )

    if price < 0:
        raise InvalidPriceError("Цена не может быть отрицательной.")

    return price
