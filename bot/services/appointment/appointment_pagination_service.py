from dataclasses import dataclass
from math import ceil

from bot.exceptions.exceptions import PaginationError
from bot.models.appointment import Appointment
from bot.repositories.appointment_repository import AppointmentRepository
from bot.utils.pagination import APPOINTMENTS_PER_PAGE


@dataclass
class AppointmentPaginationResult:
    """Результат пагинированного запроса"""
    items: list[Appointment]
    current_page: int
    total_pages: int
    total_count: int


class AppointmentPaginationService:
    """Сервис пагинации для листинга записей"""

    def __init__(self, appointment_repository: AppointmentRepository):
        self.appointment_repo = appointment_repository

    async def paginate_appointments(
        self,
        mode: str,
        page: int,
        search_data: dict = None
    ) -> AppointmentPaginationResult:
        """
        Получить страницу записей с метаданными пагинации

        Args:
            mode: 'list' - все записи, 'search' - поиск по имени, 'phone' - записи клиента
            page: номер страницы
            search_data: dict с 'full_name' для mode='search', 'client_id' для mode='phone'

        Returns:
            AppointmentPaginationResult с информацией о странице
        """
        if mode == "list":
            total_count = await self.appointment_repo.count_appointments()
            items = await self.appointment_repo.get_appointments_page(page, APPOINTMENTS_PER_PAGE)
        elif mode == "search":
            if not search_data:
                search_data = {}
            full_name = search_data.get("full_name", "")
            total_count = await self.appointment_repo.count_appointments_by_name(full_name)
            items = await self.appointment_repo.get_appointments_by_name_page(
                full_name, page, APPOINTMENTS_PER_PAGE
            )
        elif mode == "phone":
            if not search_data:
                search_data = {}
            client_id = search_data.get("client_id")
            total_count = await self.appointment_repo.count_appointments_by_client_id(client_id)
            items = await self.appointment_repo.get_appointments_by_client_id_page(
                client_id, page, APPOINTMENTS_PER_PAGE
            )
        else:
            raise PaginationError(f"Неизвестный режим пагинации: {mode}")

        total_pages = ceil(total_count / APPOINTMENTS_PER_PAGE) if total_count > 0 else 1

        page = max(1, min(page, total_pages))

        return AppointmentPaginationResult(
            items=items,
            current_page=page,
            total_pages=total_pages,
            total_count=total_count,
        )
