import re
from datetime import datetime

from bot.exceptions.appointment_exceptions import InvalidDatetimeError, InvalidPriceError, InvalidPurposeError
from bot.exceptions.user_exceptions import InvalidBirthDateError, InvalidFullNameError, InvalidPhoneError, ValidationError
from bot.utils.tools import normalize_phone

DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

BIRTH_DATE_PATTERN = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")

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

_INVALID_FULL_NAME_MESSAGE = {
    "ru": "Введите ФИ корректно (до 50 символов).\n\nНапример:\nИванов Иван, Иванов Иван Иванович.",
    "uz": "F.I.Sh.ni to'g'ri kiriting (50 belgigacha).\n\nMasalan:\nIvanov Ivan, Ivanov Ivan Ivanovich.",
}

_INVALID_PHONE_MESSAGE = {
    "ru": "Введите номер корректно.\nФорматы:\n901234567\n998901234567\n+998901234567",
    "uz": "Raqamni to'g'ri kiriting.\nFormatlar:\n901234567\n998901234567\n+998901234567",
}

_INVALID_BIRTH_DATE_FORMAT_MESSAGE = {
    "ru": "Неверный формат даты. Используйте ДД.ММ.ГГГГ, например 05.03.1990.",
    "uz": "Sana formati noto'g'ri. KK.OO.YYYY formatidan foydalaning, masalan 05.03.1990.",
}

_BIRTH_DATE_DOES_NOT_EXIST_MESSAGE = {
    "ru": "Такой даты не существует. Проверьте ввод.",
    "uz": "Bunday sana mavjud emas. Kiritilganini tekshiring.",
}

_FULL_NAME_MISSING_MESSAGE = {
    "ru": "ФИ отсутствует.",
    "uz": "F.I.Sh. kiritilmagan.",
}

_PHONE_MISSING_MESSAGE = {
    "ru": "Телефон отсутствует.",
    "uz": "Telefon raqami kiritilmagan.",
}

_INVALID_DATETIME_FORMAT_MESSAGE = {
    "ru": (
        "Ошибка формата даты и времени.\n\n"
        "Правильный формат: ГГГГ-ММ-ДД ЧЧ:ММ\n"
        "Пример: 2026-07-10 14:30\n"
        "Или: 24.07.26 12.30, 24.07.2026 12:30\n\n"
        "Или используйте русский текст:\n"
        "завтра в 3 часа, среда в 14:00, 13 сентября 15:30"
    ),
    "uz": (
        "Sana va vaqt formati xato.\n\n"
        "To'g'ri format: YYYY-OO-KK SS:DD\n"
        "Misol: 2026-07-10 14:30\n"
        "Yoki: 24.07.26 12.30, 24.07.2026 12:30\n\n"
        "Yoki rus tilidagi matndan foydalaning:\n"
        "завтра в 3 часа, среда в 14:00, 13 сентября 15:30"
    ),
}

_DATETIME_DOES_NOT_EXIST_MESSAGE = {
    "ru": "Такой даты или времени не существует. Проверьте ввод.",
    "uz": "Bunday sana yoki vaqt mavjud emas. Kiritilganini tekshiring.",
}

_INVALID_PURPOSE_MESSAGE = {
    "ru": "Опишите услугу (от 2 до 100 символов).\nНапример: Консультация, Чистка.",
    "uz": "Xizmatni tavsiflang (2 dan 100 belgigacha).\nMasalan: Konsultatsiya, Tozalash.",
}

_INVALID_PRICE_FORMAT_MESSAGE = {
    "ru": "Введите цену числом.\nНапример: 150000, 99.90.",
    "uz": "Narxni raqam bilan kiriting.\nMasalan: 150000, 99.90.",
}

_NEGATIVE_PRICE_MESSAGE = {
    "ru": "Цена не может быть отрицательной.",
    "uz": "Narx manfiy bo'lishi mumkin emas.",
}


def validate_full_name(full_name: str, pattern) -> str:
    full_name = full_name.strip()

    if len(full_name) > 50 or not pattern.fullmatch(full_name):
        raise InvalidFullNameError(_INVALID_FULL_NAME_MESSAGE)
    return full_name




def validate_phone(phone: str) -> str:
    phone = normalize_phone(phone)

    if not PHONE_PATTERN.fullmatch(phone):
        raise InvalidPhoneError(_INVALID_PHONE_MESSAGE)

    return phone


def validate_birth_date(value: str) -> str:
    value = value.strip()

    if not BIRTH_DATE_PATTERN.fullmatch(value):
        raise InvalidBirthDateError(_INVALID_BIRTH_DATE_FORMAT_MESSAGE)

    try:
        birth_date = datetime.strptime(value, "%d.%m.%Y")
    except ValueError:
        raise InvalidBirthDateError(_BIRTH_DATE_DOES_NOT_EXIST_MESSAGE)

    return birth_date.strftime("%Y-%m-%d")


def validate_fields_filled(data):
    if "full_name" not in data:
        raise ValidationError(_FULL_NAME_MISSING_MESSAGE)

    if "phone" not in data:
        raise ValidationError(_PHONE_MISSING_MESSAGE)


def validate_datetime(value: str) -> str:
    value = value.strip()

    if not DATETIME_PATTERN.fullmatch(value):
        raise InvalidDatetimeError(_INVALID_DATETIME_FORMAT_MESSAGE)

    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        raise InvalidDatetimeError(_DATETIME_DOES_NOT_EXIST_MESSAGE)

    return value


def validate_purpose(value: str) -> str:
    value = value.strip()

    if not 2 <= len(value) <= 100:
        raise InvalidPurposeError(_INVALID_PURPOSE_MESSAGE)

    return value


def validate_price(value: str) -> float:
    value = value.strip().replace(",", ".")

    try:
        price = float(value)
    except ValueError:
        raise InvalidPriceError(_INVALID_PRICE_FORMAT_MESSAGE)

    if price < 0:
        raise InvalidPriceError(_NEGATIVE_PRICE_MESSAGE)

    return price
