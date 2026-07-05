from bot.repositories.staff_repository import StaffRepository
from bot.utils.role import Role


class AuthService:
    def __init__(self, staff_repo: StaffRepository):
        self.staff_repo = staff_repo

    async def detect_role(
        self,
        telegram_user_id: int,
        clinic_id: int,
    ) -> Role:

        staff = await self.staff_repo.get_staff(telegram_user_id)

        if staff and staff.clinic_id == clinic_id:
            return Role.ADMIN

        return Role.CLIENT