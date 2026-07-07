from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import RoleError
from bot.models.clinic import Clinic
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.staff_repository import StaffRepository


async def resolve_staff_clinic(
    staff_repository: StaffRepository,
    clinic_repository: ClinicRepository,
    telegram_user_id: int,
) -> Clinic:
    staff = await staff_repository.get_staff(telegram_user_id)
    if staff is None:
        raise RoleError("Только сотрудник клиники может выполнять это действие.")

    clinic = await clinic_repository.get_clinic_by_id(staff.clinic_id)
    if clinic is None:
        raise BotException("Клиника сотрудника не найдена.")

    return clinic
