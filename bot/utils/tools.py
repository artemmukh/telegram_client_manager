import re


def normalize_phone(phone: str) -> str:
    phone = phone.strip()


    phone = re.sub(r"[\s\-\(\)]", "", phone)

    if phone.startswith("+998"):
        return phone

    if phone.startswith("998"):
        return "+" + phone

    if phone.startswith("+7"):
        return phone

    if phone.startswith("7") and len(phone) == 11:
        return "+" + phone

    if phone.startswith("8") and len(phone) == 11:
        return "+7" + phone[1:]

    if phone.startswith("+375"):
        return phone

    if phone.startswith("375") and len(phone) == 12:
        return "+" + phone

    if len(phone) == 9:
        return "+998" + phone

    return phone


def format_phone_short(phone: str) -> str:
    """Форматирует номер для отображения на кнопке: код оператора + номер через дефисы.

    +998901234567 -> "90 123-45-67". Возвращает исходный номер без изменений,
    если формат не соответствует ожидаемому (+998 и 9 цифр после него).
    """
    phone = normalize_phone(phone)

    if not phone.startswith("+998"):
        return phone

    digits = phone[4:]

    if len(digits) != 9:
        return phone

    operator = digits[:2]
    rest = digits[2:]
    return f"{operator} {rest[:3]}-{rest[3:5]}-{rest[5:7]}"