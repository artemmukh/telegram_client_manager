from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import RoleError
from bot.models.clinic import Clinic
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.staff_repository import StaffRepository

_STAFF_ONLY_ACTION_MESSAGE = {
    "ru": "Только сотрудник клиники может выполнять это действие.",
    "uz": "Bu amalni faqat klinika xodimi bajarishi mumkin.",
}

_STAFF_CLINIC_NOT_FOUND_MESSAGE = {
    "ru": "Клиника сотрудника не найдена.",
    "uz": "Xodim klinikasi topilmadi.",
}


async def resolve_staff_clinic(
    staff_repository: StaffRepository,
    clinic_repository: ClinicRepository,
    telegram_user_id: int,
) -> Clinic:
    staff = await staff_repository.get_staff(telegram_user_id)
    if staff is None:
        raise RoleError(_STAFF_ONLY_ACTION_MESSAGE)

    clinic = await clinic_repository.get_clinic_by_id(staff.clinic_id)
    if clinic is None:
        raise BotException(_STAFF_CLINIC_NOT_FOUND_MESSAGE)

    return clinic
