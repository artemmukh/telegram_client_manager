import re

from bot.exceptions.user_exceptions import InvalidFullNameError, InvalidPhoneError

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


def validate_phone(phone: str) -> None:

    if not PHONE_PATTERN.fullmatch(phone):

        raise InvalidPhoneError("Введите номер корректно.\n Формат телефона: 901234567 или 998901234567.")



async def validate_fields_filled(data, callback_query):
    if "full_name" not in data or "phone" not in data:
        await callback_query.answer("Сначала введите ФИО и номер телефона.", show_alert=True)
        return

