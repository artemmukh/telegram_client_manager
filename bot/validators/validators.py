import re

from bot.exceptions.user_exceptions import InvalidFullNameError, InvalidPhoneError, PhoneAlreadyExistsError, ValidationError
from bot.repositories.user_repository import UserRepository
from bot.utils.tools import normalize_phone

FULL_NAME_PATTERN = re.compile(
    r"^[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?"
    r"(?: [А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?){1,2}$"
)

PHONE_PATTERN = re.compile(r"^(?:\+998|998)?\d{9}$")





def validate_full_name(full_name: str) -> None:
    if not FULL_NAME_PATTERN.fullmatch(full_name.strip()):
        raise InvalidFullNameError(
            "Введите ФИО корректно.\nНапример: Иванов Иван Иванович"
        )


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




