def normalize_phone(phone: str) -> str:
    if phone.startswith("+998"):
        return phone
    if phone.startswith("998"):
        return "+" + phone
    return "+998" + phone