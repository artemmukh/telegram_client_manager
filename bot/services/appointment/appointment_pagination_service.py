import logging
from dataclasses import dataclass
from datetime import datetime
from math import ceil

from bot.exceptions.exceptions import PaginationError
from bot.models.appointment import Appointment
from bot.repositories.appointment_repository import AppointmentRepository
from bot.services.utils.date_parser import get_current_tashkent_datetime
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.pagination import APPOINTMENTS_PER_PAGE

logger = logging.getLogger(__name__)


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

    @staticmethod
    def _paginate_math(total_count: int, page: int, per_page: int) -> tuple[int, int]:
        """Вычислить total_pages и склэмпленный page для набора из total_count элементов."""
        total_pages = ceil(total_count / per_page) if total_count > 0 else 1
        page = max(1, min(page, total_pages))

        return page, total_pages

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

        page, total_pages = self._paginate_math(total_count, page, APPOINTMENTS_PER_PAGE)

        return AppointmentPaginationResult(
            items=items,
            current_page=page,
            total_pages=total_pages,
            total_count=total_count,
        )

    async def paginate_client_appointments(
        self,
        telegram_id: int,
        tab: str,
        page: int,
        per_page: int | None = None,
    ) -> AppointmentPaginationResult:
        """
        Получить страницу истории записей клиента по вкладке.

        В отличие от paginate_appointments (пагинация на уровне SQL), здесь
        фильтрация/сортировка/пагинация выполняется в памяти - это осознанное
        решение, а не недочёт, так как количество записей одного клиента
        ограничено.

        Args:
            telegram_id: telegram_user_id клиента
            tab: 'upcoming' - предстоящие, 'past' - прошедшие, 'all' - все
            page: номер страницы
        """
        per_page = per_page or APPOINTMENTS_PER_PAGE

        appointments = await self.appointment_repo.get_appointments_by_telegram_id(telegram_id)
        now = get_current_tashkent_datetime()

        upcoming = []
        past = []

        for appointment in appointments:
            try:
                appointment_dt = datetime.fromisoformat(appointment.datetime)
            except ValueError:
                logger.warning(
                    f"Не удалось разобрать дату записи {appointment.id}: {appointment.datetime!r}"
                )
                appointment_dt = datetime.min

            if appointment_dt >= now:
                upcoming.append((appointment_dt, appointment))
            else:
                past.append((appointment_dt, appointment))

        # Статус записи не влияет на распределение по вкладкам - деление
        # чисто по времени, поэтому отменённая будущая запись всё ещё
        # считается "предстоящей". Это ожидаемое поведение.
        upcoming.sort(key=lambda pair: (pair[0], pair[1].id))
        past.sort(key=lambda pair: (pair[0], pair[1].id), reverse=True)

        if tab == "upcoming":
            filtered = [appointment for _, appointment in upcoming]
        elif tab == "past":
            filtered = [appointment for _, appointment in past]
        elif tab == "all":
            filtered = [appointment for _, appointment in upcoming] + [appointment for _, appointment in past]
        else:
            raise PaginationError(f"Неизвестная вкладка истории: {tab}")

        total_count = len(filtered)
        page, total_pages = self._paginate_math(total_count, page, per_page)

        items = filtered[(page - 1) * per_page: page * per_page]

        return AppointmentPaginationResult(
            items=items,
            current_page=page,
            total_pages=total_pages,
            total_count=total_count,
        )

    async def paginate_active_client_appointments(
        self,
        telegram_id: int,
        page: int,
        per_page: int | None = None,
    ) -> AppointmentPaginationResult:
        """
        Получить страницу активных (будущих, PENDING/CONFIRMED) записей клиента
        для сценария управления записью.
        """
        per_page = per_page or APPOINTMENTS_PER_PAGE

        appointments = await self.appointment_repo.get_appointments_by_telegram_id(telegram_id)
        now = get_current_tashkent_datetime()

        active = []

        for appointment in appointments:
            try:
                appointment_dt = datetime.fromisoformat(appointment.datetime)
            except ValueError:
                logger.warning(
                    f"Не удалось разобрать дату записи {appointment.id}: {appointment.datetime!r}"
                )
                continue

            if appointment_dt < now:
                continue

            if appointment.status not in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED):
                continue

            active.append((appointment_dt, appointment))

        active.sort(key=lambda pair: (pair[0], pair[1].id))
        filtered = [appointment for _, appointment in active]

        total_count = len(filtered)
        page, total_pages = self._paginate_math(total_count, page, per_page)

        items = filtered[(page - 1) * per_page: page * per_page]

        return AppointmentPaginationResult(
            items=items,
            current_page=page,
            total_pages=total_pages,
            total_count=total_count,
        )
