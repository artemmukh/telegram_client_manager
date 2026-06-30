def normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "")

    if phone.startswith("998"):
        phone = "+" + phone

    return phone