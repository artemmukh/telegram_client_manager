from datetime import timedelta

import pytest

from bot.exceptions.exceptions import PaginationError
from bot.models.appointment import Appointment
from bot.services.appointment.appointment_pagination_service import (
    AppointmentPaginationService,
)
from bot.services.utils.date_parser import get_current_tashkent_datetime
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.pagination import APPOINTMENTS_PER_PAGE


class FakeAppointmentRepository:
    """Мнимый репозиторий записей для юнит-тестов сервиса пагинации.

    Хранит фиксированные "ответы" на страничные/count-запросы и
    записывает, с какими аргументами эти методы вызывались, чтобы тесты
    могли проверить маршрутизацию по режимам (mode).
    """

    def __init__(
        self,
        total_count: int = 0,
        page_items: list[Appointment] | None = None,
    ):
        self.total_count = total_count
        self.page_items = list(page_items or [])
        self.calls: list[tuple] = []

    async def count_appointments(self) -> int:
        self.calls.append(("count_appointments",))
        return self.total_count

    async def get_appointments_page(self, page: int, per_page: int) -> list[Appointment]:
        self.calls.append(("get_appointments_page", page, per_page))
        return self.page_items

    async def count_appointments_by_name(self, full_name: str) -> int:
        self.calls.append(("count_appointments_by_name", full_name))
        return self.total_count

    async def get_appointments_by_name_page(
        self, full_name: str, page: int, per_page: int
    ) -> list[Appointment]:
        self.calls.append(("get_appointments_by_name_page", full_name, page, per_page))
        return self.page_items

    async def count_appointments_by_client_id(self, client_id: int) -> int:
        self.calls.append(("count_appointments_by_client_id", client_id))
        return self.total_count

    async def get_appointments_by_client_id_page(
        self, client_id: int, page: int, per_page: int
    ) -> list[Appointment]:
        self.calls.append(("get_appointments_by_client_id_page", client_id, page, per_page))
        return self.page_items

    async def get_appointments_by_telegram_id(self, telegram_user_id: int) -> list[Appointment]:
        self.calls.append(("get_appointments_by_telegram_id", telegram_user_id))
        return self.page_items


def _appointment(appointment_id: int) -> Appointment:
    return Appointment(
        clinic_id=1,
        client_id=7,
        datetime="2026-07-10 14:30",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        id=appointment_id,
    )


# --- mode="list" ---

@pytest.mark.asyncio
async def test_paginate_list_mode_returns_all_appointments():
    items = [_appointment(1), _appointment(2)]
    repo = FakeAppointmentRepository(total_count=2, page_items=items)
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("list", 1)

    assert result.items == items
    assert result.current_page == 1
    assert result.total_count == 2
    assert result.total_pages == 1
    assert ("count_appointments",) in repo.calls
    assert ("get_appointments_page", 1, APPOINTMENTS_PER_PAGE) in repo.calls


# --- mode="search" ---

@pytest.mark.asyncio
async def test_paginate_search_mode_routes_full_name_to_repository():
    items = [_appointment(1)]
    repo = FakeAppointmentRepository(total_count=1, page_items=items)
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("search", 1, {"full_name": "Иванов"})

    assert result.items == items
    assert result.total_count == 1
    assert ("count_appointments_by_name", "Иванов") in repo.calls
    assert ("get_appointments_by_name_page", "Иванов", 1, APPOINTMENTS_PER_PAGE) in repo.calls


@pytest.mark.asyncio
async def test_paginate_search_mode_defaults_full_name_when_search_data_missing():
    repo = FakeAppointmentRepository(total_count=0, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("search", 1, None)

    assert result.total_count == 0
    assert ("count_appointments_by_name", "") in repo.calls
    assert ("get_appointments_by_name_page", "", 1, APPOINTMENTS_PER_PAGE) in repo.calls


# --- mode="phone" ---

@pytest.mark.asyncio
async def test_paginate_phone_mode_routes_client_id_to_repository():
    items = [_appointment(1), _appointment(2)]
    repo = FakeAppointmentRepository(total_count=2, page_items=items)
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("phone", 1, {"client_id": 7})

    assert result.items == items
    assert result.total_count == 2
    assert ("count_appointments_by_client_id", 7) in repo.calls
    assert ("get_appointments_by_client_id_page", 7, 1, APPOINTMENTS_PER_PAGE) in repo.calls


@pytest.mark.asyncio
async def test_paginate_phone_mode_defaults_client_id_when_search_data_missing():
    repo = FakeAppointmentRepository(total_count=0, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("phone", 1, None)

    assert ("count_appointments_by_client_id", None) in repo.calls
    assert ("get_appointments_by_client_id_page", None, 1, APPOINTMENTS_PER_PAGE) in repo.calls


# --- unknown mode ---

@pytest.mark.asyncio
async def test_paginate_unknown_mode_raises_pagination_error():
    repo = FakeAppointmentRepository()
    service = AppointmentPaginationService(repo)

    with pytest.raises(PaginationError):
        await service.paginate_appointments("unknown", 1)


# --- total_pages / page clamping ---

@pytest.mark.asyncio
async def test_total_pages_computed_with_ceil():
    repo = FakeAppointmentRepository(total_count=21, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("list", 1)

    assert result.total_pages == 3  # ceil(21 / 10)


@pytest.mark.asyncio
async def test_page_clamped_to_total_pages_when_too_high():
    repo = FakeAppointmentRepository(total_count=15, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("list", 999)

    assert result.total_pages == 2  # ceil(15 / 10)
    assert result.current_page == 2


@pytest.mark.asyncio
async def test_page_clamped_to_one_when_below_range():
    repo = FakeAppointmentRepository(total_count=15, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("list", 0)

    assert result.current_page == 1


@pytest.mark.asyncio
async def test_empty_result_set_returns_valid_result_with_single_page():
    repo = FakeAppointmentRepository(total_count=0, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("list", 1)

    assert result.total_count == 0
    assert result.total_pages == 1
    assert result.current_page == 1
    assert result.items == []


# --- paginate_client_appointments ---

def _appointment_at(appointment_id: int, dt, status: AppointmentStatus = AppointmentStatus.PENDING) -> Appointment:
    return Appointment(
        clinic_id=1,
        client_id=7,
        datetime=dt.isoformat(),
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=status,
        id=appointment_id,
    )


@pytest.mark.asyncio
async def test_paginate_client_appointments_upcoming_only_ascending_order():
    now = get_current_tashkent_datetime()
    a1 = _appointment_at(1, now + timedelta(days=2))
    a2 = _appointment_at(2, now + timedelta(days=1))
    a3 = _appointment_at(3, now - timedelta(days=1))
    repo = FakeAppointmentRepository(page_items=[a1, a2, a3])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_client_appointments(123, "upcoming", 1)

    assert [a.id for a in result.items] == [2, 1]
    assert result.total_count == 2
    assert result.total_pages == 1


@pytest.mark.asyncio
async def test_paginate_client_appointments_past_only_descending_order():
    now = get_current_tashkent_datetime()
    a1 = _appointment_at(1, now - timedelta(days=2))
    a2 = _appointment_at(2, now - timedelta(days=1))
    a3 = _appointment_at(3, now + timedelta(days=1))
    repo = FakeAppointmentRepository(page_items=[a1, a2, a3])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_client_appointments(123, "past", 1)

    assert [a.id for a in result.items] == [2, 1]
    assert result.total_count == 2


@pytest.mark.asyncio
async def test_paginate_client_appointments_all_tab_is_upcoming_then_past():
    now = get_current_tashkent_datetime()
    upcoming = _appointment_at(1, now + timedelta(days=1))
    past = _appointment_at(2, now - timedelta(days=1))
    repo = FakeAppointmentRepository(page_items=[past, upcoming])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_client_appointments(123, "all", 1)

    assert [a.id for a in result.items] == [1, 2]
    assert result.total_count == 2


@pytest.mark.asyncio
async def test_paginate_client_appointments_unknown_tab_raises_pagination_error():
    repo = FakeAppointmentRepository(page_items=[])
    service = AppointmentPaginationService(repo)

    with pytest.raises(PaginationError):
        await service.paginate_client_appointments(123, "unknown", 1)


@pytest.mark.asyncio
async def test_paginate_client_appointments_empty_result_returns_single_page():
    repo = FakeAppointmentRepository(page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_client_appointments(123, "all", 1)

    assert result.total_count == 0
    assert result.total_pages == 1
    assert result.current_page == 1
    assert result.items == []


@pytest.mark.asyncio
async def test_paginate_client_appointments_slices_across_page_boundary():
    now = get_current_tashkent_datetime()
    appointments = [
        _appointment_at(i, now + timedelta(days=i))
        for i in range(1, APPOINTMENTS_PER_PAGE + 3)
    ]
    repo = FakeAppointmentRepository(page_items=appointments)
    service = AppointmentPaginationService(repo)

    page_1 = await service.paginate_client_appointments(123, "upcoming", 1)
    page_2 = await service.paginate_client_appointments(123, "upcoming", 2)

    assert len(page_1.items) == APPOINTMENTS_PER_PAGE
    assert len(page_2.items) == 2
    assert page_1.total_pages == 2
    assert [a.id for a in page_1.items] == list(range(1, APPOINTMENTS_PER_PAGE + 1))
    assert [a.id for a in page_2.items] == [APPOINTMENTS_PER_PAGE + 1, APPOINTMENTS_PER_PAGE + 2]
