import re


def normalize_phone(phone: str) -> str:
    phone = phone.strip()


    phone = re.sub(r"[\s\-\(\)]", "", phone)

    if phone.startswith("+998"):
        return phone

    if phone.startswith("998"):
        return "+" + phone

    if len(phone) == 9:
        return "+998" + phone

    return phone