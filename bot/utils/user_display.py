from bot.models.user import User


def format_clinic_label(clinic_name: str | None) -> str:
    if clinic_name:
        return clinic_name
    return "Без клиники"


def format_clinic_field(clinic_name: str | None) -> str:
    if clinic_name:
        return clinic_name
    return "Не назначена"


def format_user_type(user: User) -> str:
    if user.role == "admin":
        role = "администратор"
    else:
        role = "клиент"

    return f"{role} ({format_clinic_label(user.clinic_name)})"
