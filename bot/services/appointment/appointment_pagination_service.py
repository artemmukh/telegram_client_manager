import logging
from dataclasses import dataclass
from datetime import datetime
from math import ceil

from bot.exceptions.exceptions import PaginationError
from bot.models.appointment import Appointment
from bot.repositories.appointment_repository import AppointmentRepository
from bot.services.utils.date_parser import get_current_tashkent_datetime, is_appointment_upcoming
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

    _STATUS_TABS = {
        "confirmed": AppointmentStatus.CONFIRMED,
        "pending": AppointmentStatus.PENDING,
        "cancelled": AppointmentStatus.CANCELLED,
        "no_show": AppointmentStatus.NO_SHOW,
        "completed": AppointmentStatus.COMPLETED,
        "expired": AppointmentStatus.EXPIRED,
    }

    def __init__(self, appointment_repository: AppointmentRepository):
        self.appointment_repo = appointment_repository

    @staticmethod
    def _paginate_math(total_count: int, page: int, per_page: int) -> tuple[int, int]:
        """Вычислить total_pages и склэмпленный page для набора из total_count элементов."""
        total_pages = ceil(total_count / per_page) if total_count > 0 else 1
        page = max(1, min(page, total_pages))

        return page, total_pages

    def _sort_by_datetime(self, appointments: list[Appointment], reverse: bool) -> list[Appointment]:
        dated = []

        for appointment in appointments:
            try:
                appointment_dt = datetime.fromisoformat(appointment.datetime)
            except ValueError:
                logger.warning(
                    f"Не удалось разобрать дату записи {appointment.id}: {appointment.datetime!r}"
                )
                appointment_dt = datetime.min

            dated.append((appointment_dt, appointment))

        dated.sort(key=lambda pair: (pair[0], pair[1].id), reverse=reverse)
        return [appointment for _, appointment in dated]

    def _sort_by_created_at(self, appointments: list[Appointment], reverse: bool) -> list[Appointment]:
        dated = []

        for appointment in appointments:
            try:
                created_at = (
                    datetime.fromisoformat(appointment.created_at)
                    if appointment.created_at
                    else datetime.min
                )
            except ValueError:
                logger.warning(
                    f"Не удалось разобрать дату создания записи {appointment.id}: {appointment.created_at!r}"
                )
                created_at = datetime.min

            dated.append((created_at, appointment))

        dated.sort(key=lambda pair: (pair[0], pair[1].id), reverse=reverse)
        return [appointment for _, appointment in dated]

    def _sort_by_status_updated_at(self, appointments: list[Appointment], reverse: bool) -> list[Appointment]:
        dated = []

        for appointment in appointments:
            value = appointment.status_updated_at or appointment.created_at
            try:
                status_updated_at = datetime.fromisoformat(value) if value else datetime.min
            except ValueError:
                logger.warning(
                    f"Не удалось разобрать дату смены статуса записи {appointment.id}: {value!r}"
                )
                status_updated_at = datetime.min

            dated.append((status_updated_at, appointment))

        dated.sort(key=lambda pair: (pair[0], pair[1].id), reverse=reverse)
        return [appointment for _, appointment in dated]

    def _sort_bucket_by_status(
        self, appointments: list[Appointment], status: AppointmentStatus
    ) -> list[Appointment]:
        if status == AppointmentStatus.CONFIRMED:
            return self._sort_by_datetime(appointments, reverse=False)
        if status == AppointmentStatus.PENDING:
            return self._sort_by_created_at(appointments, reverse=True)
        return self._sort_by_status_updated_at(appointments, reverse=True)

    def _filter_by_tab(self, appointments: list[Appointment], tab: str) -> list[Appointment]:
        if tab not in self._STATUS_TABS:
            raise PaginationError(f"Неизвестная вкладка: {tab}")

        status = self._STATUS_TABS[tab]
        bucket = [appointment for appointment in appointments if appointment.status == status]
        return self._sort_bucket_by_status(bucket, status)

    async def paginate_appointments(
        self,
        mode: str,
        page: int,
        clinic_id: int,
        doctor_id: int | None = None,
        search_data: dict = None,
        tab: str = "confirmed",
    ) -> AppointmentPaginationResult:
        """
        Получить страницу записей с метаданными пагинации

        Args:
            mode: 'list' - все записи, 'search' - поиск по имени, 'phone' - записи клиента
            page: номер страницы
            clinic_id: клиника, к которой скоупится выборка
            doctor_id: если задан, ограничивает выборку записями этого врача
            search_data: dict с 'full_name' для mode='search', 'client_id' для mode='phone'
            tab: вкладка по статусу ('confirmed'/'pending'/'cancelled'/'no_show'/'completed'/'expired'),
                применяется только к mode='search' и mode='phone'

        Returns:
            AppointmentPaginationResult с информацией о странице
        """
        ordered = None

        if mode == "list":
            total_count = await self.appointment_repo.count_appointments(clinic_id, doctor_id)
            items = await self.appointment_repo.get_appointments_page(
                page, clinic_id, doctor_id, APPOINTMENTS_PER_PAGE
            )
        elif mode == "search":
            full_name = (search_data or {}).get("full_name", "")
            appointments = await self.appointment_repo.get_appointments_by_name(full_name, clinic_id, doctor_id)
            ordered = self._filter_by_tab(appointments, tab)
            total_count = len(ordered)
        elif mode == "phone":
            client_id = (search_data or {}).get("client_id")
            appointments = await self.appointment_repo.get_appointments_by_client_id(
                client_id, clinic_id, doctor_id
            )
            ordered = self._filter_by_tab(appointments, tab)
            total_count = len(ordered)
        else:
            raise PaginationError(f"Неизвестный режим пагинации: {mode}")

        page, total_pages = self._paginate_math(total_count, page, APPOINTMENTS_PER_PAGE)

        if ordered is not None:
            items = ordered[(page - 1) * APPOINTMENTS_PER_PAGE: page * APPOINTMENTS_PER_PAGE]

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
            tab: вкладка по статусу ('confirmed'/'pending'/'cancelled'/'no_show'/'completed'/'expired')
            page: номер страницы
        """
        per_page = per_page or APPOINTMENTS_PER_PAGE

        appointments = await self.appointment_repo.get_appointments_by_telegram_id(telegram_id)
        filtered = self._filter_by_tab(appointments, tab)

        total_count = len(filtered)
        page, total_pages = self._paginate_math(total_count, page, per_page)

        items = filtered[(page - 1) * per_page: page * per_page]

        return AppointmentPaginationResult(
            items=items,
            current_page=page,
            total_pages=total_pages,
            total_count=total_count,
        )

    async def paginate_all_appointments_by_tab(
        self,
        tab: str,
        page: int,
        clinic_id: int,
        doctor_id: int | None = None,
        per_page: int | None = None,
    ) -> AppointmentPaginationResult:
        """
        Получить страницу списка всех записей (админ, mode="list") по вкладке.

        В отличие от paginate_client_appointments, здесь используется
        пагинация на уровне SQL - таблица записей неограниченно растёт,
        поэтому загружать её целиком в память на каждое переключение
        вкладки/страницы нельзя.

        Args:
            tab: вкладка по статусу ('confirmed'/'pending'/'cancelled'/'no_show'/'completed'/'expired')
            page: номер страницы
            clinic_id: клиника, к которой скоупится выборка
            doctor_id: если задан, ограничивает выборку записями этого врача
        """
        if tab not in self._STATUS_TABS:
            raise PaginationError(f"Неизвестная вкладка: {tab}")

        per_page = per_page or APPOINTMENTS_PER_PAGE
        status = self._STATUS_TABS[tab]

        total_count = await self.appointment_repo.count_appointments_by_status(status, clinic_id, doctor_id)
        page, total_pages = self._paginate_math(total_count, page, per_page)

        items = await self.appointment_repo.get_appointments_by_status_page(
            status, page, clinic_id, doctor_id, per_page
        )

        return AppointmentPaginationResult(
            items=items,
            current_page=page,
            total_pages=total_pages,
            total_count=total_count,
        )

    async def paginate_appointments_by_date_and_tab(
        self,
        date_str: str,
        tab: str,
        page: int,
        clinic_id: int,
        doctor_id: int | None = None,
        per_page: int | None = None,
    ) -> AppointmentPaginationResult:
        """
        Получить страницу записей на конкретную дату (календарь) по вкладке.

        В отличие от paginate_all_appointments_by_tab, сортировка всегда идёт
        по времени приёма (a.datetime ASC), а не по стандартной для вкладки -
        весь смысл календарного представления в хронологическом порядке
        записей за выбранный день.

        Args:
            date_str: дата в формате 'YYYY-MM-DD'
            tab: вкладка по статусу ('confirmed'/'pending'/'cancelled'/'no_show'/'completed'/'expired')
            page: номер страницы
            clinic_id: клиника, к которой скоупится выборка
            doctor_id: если задан, ограничивает выборку записями этого врача
        """
        if tab not in self._STATUS_TABS:
            raise PaginationError(f"Неизвестная вкладка: {tab}")

        per_page = per_page or APPOINTMENTS_PER_PAGE
        status = self._STATUS_TABS[tab]

        total_count = await self.appointment_repo.count_appointments_by_date_and_status(
            date_str, status, clinic_id, doctor_id
        )
        page, total_pages = self._paginate_math(total_count, page, per_page)

        items = await self.appointment_repo.get_appointments_by_date_and_status_page(
            date_str, status, page, clinic_id, doctor_id, per_page
        )

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
            if appointment.status not in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED):
                continue

            if not is_appointment_upcoming(appointment, now):
                continue

            relevant_datetime = (
                appointment.proposed_datetime
                if appointment.proposed_datetime is not None
                else appointment.datetime
            )
            appointment_dt = datetime.fromisoformat(relevant_datetime)

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
