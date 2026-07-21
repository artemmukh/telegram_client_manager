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

    Хранит фиксированные "ответы" на запросы и записывает, с какими
    аргументами эти методы вызывались, чтобы тесты могли проверить
    маршрутизацию по режимам (mode).
    """

    def __init__(
        self,
        total_count: int = 0,
        page_items: list[Appointment] | None = None,
    ):
        self.total_count = total_count
        self.page_items = list(page_items or [])
        self.calls: list[tuple] = []

    async def count_appointments(self, clinic_id: int, doctor_id: int | None = None) -> int:
        self.calls.append(("count_appointments", clinic_id, doctor_id))
        return self.total_count

    async def get_appointments_page(
        self, page: int, clinic_id: int, doctor_id: int | None, per_page: int
    ) -> list[Appointment]:
        self.calls.append(("get_appointments_page", page, clinic_id, doctor_id, per_page))
        return self.page_items

    async def count_appointments_by_name_and_status(
        self,
        full_name: str,
        status: AppointmentStatus,
        clinic_id: int,
        doctor_id: int | None = None,
        tab_bucket: bool = False,
    ) -> int:
        self.calls.append(
            ("count_appointments_by_name_and_status", full_name, status, clinic_id, doctor_id, tab_bucket)
        )
        return self.total_count

    async def get_appointments_by_name_and_status_page(
        self,
        full_name: str,
        status: AppointmentStatus,
        page: int,
        clinic_id: int,
        doctor_id: int | None = None,
        per_page: int = 10,
        tab_bucket: bool = False,
    ) -> list[Appointment]:
        self.calls.append(
            (
                "get_appointments_by_name_and_status_page",
                full_name, status, page, clinic_id, doctor_id, per_page, tab_bucket,
            )
        )
        return self.page_items

    async def get_appointments_by_client_id(
        self, client_id: int, clinic_id: int, doctor_id: int | None = None
    ) -> list[Appointment]:
        self.calls.append(("get_appointments_by_client_id", client_id, clinic_id, doctor_id))
        return self.page_items

    async def get_appointments_by_telegram_id(self, telegram_user_id: int) -> list[Appointment]:
        self.calls.append(("get_appointments_by_telegram_id", telegram_user_id))
        return self.page_items

    async def get_appointments_by_status_page(
        self,
        status: AppointmentStatus,
        page: int,
        clinic_id: int,
        doctor_id: int | None,
        per_page: int,
        tab_bucket: bool = False,
    ) -> list[Appointment]:
        self.calls.append(
            ("get_appointments_by_status_page", status, page, clinic_id, doctor_id, per_page, tab_bucket)
        )
        return self.page_items

    async def count_appointments_by_status(
        self, status: AppointmentStatus, clinic_id: int, doctor_id: int | None = None, tab_bucket: bool = False
    ) -> int:
        self.calls.append(("count_appointments_by_status", status, clinic_id, doctor_id, tab_bucket))
        return self.total_count

    async def get_appointments_by_date_and_status_page(
        self,
        date_str: str,
        status: AppointmentStatus,
        page: int,
        clinic_id: int,
        doctor_id: int | None,
        per_page: int,
        tab_bucket: bool = False,
    ) -> list[Appointment]:
        self.calls.append(
            (
                "get_appointments_by_date_and_status_page",
                date_str, status, page, clinic_id, doctor_id, per_page, tab_bucket,
            )
        )
        return self.page_items

    async def count_appointments_by_date_and_status(
        self,
        date_str: str,
        status: AppointmentStatus,
        clinic_id: int,
        doctor_id: int | None = None,
        tab_bucket: bool = False,
    ) -> int:
        self.calls.append(("count_appointments_by_date_and_status", date_str, status, clinic_id, doctor_id, tab_bucket))
        return self.total_count


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

    result = await service.paginate_appointments("list", 1, clinic_id=1)

    assert result.items == items
    assert result.current_page == 1
    assert result.total_count == 2
    assert result.total_pages == 1
    assert ("count_appointments", 1, None) in repo.calls
    assert ("get_appointments_page", 1, 1, None, APPOINTMENTS_PER_PAGE) in repo.calls


@pytest.mark.asyncio
async def test_paginate_list_mode_forwards_concrete_doctor_id_to_repository():
    """Admin_visibility_scope feature: an 'own'-scope admin's doctor_id must reach
    the repository call, not just the clinic_id."""
    repo = FakeAppointmentRepository(total_count=0, page_items=[])
    service = AppointmentPaginationService(repo)

    await service.paginate_appointments("list", 1, clinic_id=1, doctor_id=5)

    assert ("count_appointments", 1, 5) in repo.calls
    assert ("get_appointments_page", 1, 1, 5, APPOINTMENTS_PER_PAGE) in repo.calls


# --- mode="search" ---
# NOTE: mode="search" is backed by SQL-level pagination (see
# tests/test_appointment_repository.py for tab-bucket/sort-order correctness
# against a real SQLite connection). These tests only verify routing: correct
# status resolved from tab, correct repository calls made, items passed
# through untouched.

@pytest.mark.asyncio
async def test_paginate_search_mode_routes_full_name_to_repository_and_filters_by_tab():
    items = [_appointment(1)]
    repo = FakeAppointmentRepository(total_count=1, page_items=items)
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments(
        "search", 1, clinic_id=1, search_data={"full_name": "Иванов"}, tab="pending"
    )

    assert result.items == items
    assert result.total_count == 1
    assert (
        "count_appointments_by_name_and_status",
        "Иванов", AppointmentStatus.PENDING, 1, None, True,
    ) in repo.calls
    assert (
        "get_appointments_by_name_and_status_page",
        "Иванов", AppointmentStatus.PENDING, 1, 1, None, APPOINTMENTS_PER_PAGE, True,
    ) in repo.calls


@pytest.mark.asyncio
async def test_paginate_search_mode_defaults_full_name_when_search_data_missing():
    repo = FakeAppointmentRepository(total_count=0, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("search", 1, clinic_id=1, search_data=None, tab="pending")

    assert result.total_count == 0
    assert (
        "count_appointments_by_name_and_status",
        "", AppointmentStatus.PENDING, 1, None, True,
    ) in repo.calls
    assert (
        "get_appointments_by_name_and_status_page",
        "", AppointmentStatus.PENDING, 1, 1, None, APPOINTMENTS_PER_PAGE, True,
    ) in repo.calls


@pytest.mark.asyncio
async def test_paginate_search_mode_forwards_concrete_doctor_id_to_repository():
    repo = FakeAppointmentRepository(page_items=[])
    service = AppointmentPaginationService(repo)

    await service.paginate_appointments(
        "search", 1, clinic_id=1, doctor_id=5, search_data={"full_name": "Иванов"}, tab="pending"
    )

    assert (
        "count_appointments_by_name_and_status",
        "Иванов", AppointmentStatus.PENDING, 1, 5, True,
    ) in repo.calls
    assert (
        "get_appointments_by_name_and_status_page",
        "Иванов", AppointmentStatus.PENDING, 1, 1, 5, APPOINTMENTS_PER_PAGE, True,
    ) in repo.calls


# --- mode="phone" ---

@pytest.mark.asyncio
async def test_paginate_phone_mode_routes_client_id_to_repository():
    items = [_appointment(1), _appointment(2)]
    repo = FakeAppointmentRepository(total_count=2, page_items=items)
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("phone", 1, clinic_id=1, search_data={"client_id": 7}, tab="pending")

    assert {a.id for a in result.items} == {a.id for a in items}
    assert result.total_count == 2
    assert ("get_appointments_by_client_id", 7, 1, None) in repo.calls


@pytest.mark.asyncio
async def test_paginate_phone_mode_defaults_client_id_when_search_data_missing():
    repo = FakeAppointmentRepository(total_count=0, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("phone", 1, clinic_id=1, search_data=None)

    assert ("get_appointments_by_client_id", None, 1, None) in repo.calls


@pytest.mark.asyncio
async def test_paginate_phone_mode_filters_by_status_tab():
    pending = _appointment(1)
    pending.status = AppointmentStatus.PENDING
    cancelled = _appointment(2)
    cancelled.status = AppointmentStatus.CANCELLED
    repo = FakeAppointmentRepository(page_items=[pending, cancelled])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("phone", 1, clinic_id=1, search_data={"client_id": 7}, tab="pending")

    assert [a.id for a in result.items] == [1]


@pytest.mark.asyncio
async def test_paginate_phone_mode_confirmed_tab_excludes_negotiating_appointment():
    plain_confirmed = _appointment(1)
    plain_confirmed.status = AppointmentStatus.CONFIRMED
    negotiating = _appointment(2)
    negotiating.status = AppointmentStatus.CONFIRMED
    negotiating.proposed_datetime = "2026-08-01 10:00"
    repo = FakeAppointmentRepository(page_items=[plain_confirmed, negotiating])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments(
        "phone", 1, clinic_id=1, search_data={"client_id": 7}, tab="confirmed"
    )

    assert [a.id for a in result.items] == [1]


@pytest.mark.asyncio
async def test_paginate_phone_mode_pending_tab_includes_negotiating_confirmed_appointment():
    plain_pending = _appointment(1)
    negotiating = _appointment(2)
    negotiating.status = AppointmentStatus.CONFIRMED
    negotiating.proposed_datetime = "2026-08-01 10:00"
    repo = FakeAppointmentRepository(page_items=[plain_pending, negotiating])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments(
        "phone", 1, clinic_id=1, search_data={"client_id": 7}, tab="pending"
    )

    assert {a.id for a in result.items} == {1, 2}


@pytest.mark.asyncio
async def test_paginate_phone_mode_forwards_concrete_doctor_id_to_repository():
    repo = FakeAppointmentRepository(page_items=[])
    service = AppointmentPaginationService(repo)

    await service.paginate_appointments(
        "phone", 1, clinic_id=1, doctor_id=5, search_data={"client_id": 7}, tab="pending"
    )

    assert ("get_appointments_by_client_id", 7, 1, 5) in repo.calls


# --- unknown mode ---

@pytest.mark.asyncio
async def test_paginate_unknown_mode_raises_pagination_error():
    repo = FakeAppointmentRepository()
    service = AppointmentPaginationService(repo)

    with pytest.raises(PaginationError):
        await service.paginate_appointments("unknown", 1, clinic_id=1)


# --- total_pages / page clamping ---

@pytest.mark.asyncio
async def test_total_pages_computed_with_ceil():
    repo = FakeAppointmentRepository(total_count=21, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("list", 1, clinic_id=1)

    assert result.total_pages == 3  # ceil(21 / 10)


@pytest.mark.asyncio
async def test_page_clamped_to_total_pages_when_too_high():
    repo = FakeAppointmentRepository(total_count=15, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("list", 999, clinic_id=1)

    assert result.total_pages == 2  # ceil(15 / 10)
    assert result.current_page == 2


@pytest.mark.asyncio
async def test_page_clamped_to_one_when_below_range():
    repo = FakeAppointmentRepository(total_count=15, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("list", 0, clinic_id=1)

    assert result.current_page == 1


@pytest.mark.asyncio
async def test_empty_result_set_returns_valid_result_with_single_page():
    repo = FakeAppointmentRepository(total_count=0, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments("list", 1, clinic_id=1)

    assert result.total_count == 0
    assert result.total_pages == 1
    assert result.current_page == 1
    assert result.items == []


# --- paginate_client_appointments ---

def _appointment_at(
    appointment_id: int,
    dt,
    status: AppointmentStatus = AppointmentStatus.PENDING,
    created_at=None,
    status_updated_at=None,
    client_id: int = 7,
) -> Appointment:
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        datetime=dt.isoformat(),
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=status,
        id=appointment_id,
        created_at=created_at.isoformat() if created_at is not None else None,
        status_updated_at=status_updated_at.isoformat() if status_updated_at is not None else None,
    )


@pytest.mark.asyncio
async def test_paginate_client_appointments_confirmed_tab_excludes_negotiating_appointment():
    now = get_current_tashkent_datetime()
    plain_confirmed = _appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.CONFIRMED)
    negotiating = _appointment_at(2, now + timedelta(days=2), status=AppointmentStatus.CONFIRMED)
    negotiating.proposed_datetime = (now + timedelta(days=5)).isoformat()
    repo = FakeAppointmentRepository(page_items=[plain_confirmed, negotiating])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_client_appointments(123, "confirmed", 1)

    assert [a.id for a in result.items] == [1]
    assert result.total_count == 1


@pytest.mark.asyncio
async def test_paginate_client_appointments_pending_tab_includes_negotiating_confirmed_appointment():
    now = get_current_tashkent_datetime()
    plain_pending = _appointment_at(1, now, status=AppointmentStatus.PENDING, created_at=now - timedelta(days=1))
    negotiating = _appointment_at(2, now, status=AppointmentStatus.CONFIRMED, created_at=now)
    negotiating.proposed_datetime = (now + timedelta(days=5)).isoformat()
    repo = FakeAppointmentRepository(page_items=[plain_pending, negotiating])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_client_appointments(123, "pending", 1)

    assert {a.id for a in result.items} == {1, 2}
    assert result.total_count == 2


@pytest.mark.asyncio
async def test_paginate_client_appointments_confirmed_tab_ascending_by_datetime():
    now = get_current_tashkent_datetime()
    a1 = _appointment_at(1, now + timedelta(days=2), status=AppointmentStatus.CONFIRMED)
    a2 = _appointment_at(2, now + timedelta(days=1), status=AppointmentStatus.CONFIRMED)
    a3 = _appointment_at(3, now - timedelta(days=1), status=AppointmentStatus.PENDING)
    repo = FakeAppointmentRepository(page_items=[a1, a2, a3])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_client_appointments(123, "confirmed", 1)

    assert [a.id for a in result.items] == [2, 1]
    assert result.total_count == 2
    assert result.total_pages == 1


@pytest.mark.asyncio
async def test_paginate_client_appointments_pending_tab_descending_by_created_at():
    now = get_current_tashkent_datetime()
    a1 = _appointment_at(1, now, status=AppointmentStatus.PENDING, created_at=now - timedelta(days=2))
    a2 = _appointment_at(2, now, status=AppointmentStatus.PENDING, created_at=now - timedelta(days=1))
    a3 = _appointment_at(3, now, status=AppointmentStatus.CONFIRMED, created_at=now)
    repo = FakeAppointmentRepository(page_items=[a1, a2, a3])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_client_appointments(123, "pending", 1)

    assert [a.id for a in result.items] == [2, 1]
    assert result.total_count == 2


@pytest.mark.asyncio
async def test_paginate_client_appointments_cancelled_tab_descending_by_status_updated_at():
    now = get_current_tashkent_datetime()
    a1 = _appointment_at(
        1, now, status=AppointmentStatus.CANCELLED, status_updated_at=now - timedelta(days=2)
    )
    a2 = _appointment_at(
        2, now, status=AppointmentStatus.CANCELLED, status_updated_at=now - timedelta(days=1)
    )
    repo = FakeAppointmentRepository(page_items=[a1, a2])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_client_appointments(123, "cancelled", 1)

    assert [a.id for a in result.items] == [2, 1]


@pytest.mark.asyncio
async def test_paginate_client_appointments_expired_tab_descending_by_status_updated_at():
    now = get_current_tashkent_datetime()
    older = _appointment_at(
        1, now, status=AppointmentStatus.EXPIRED, status_updated_at=now - timedelta(days=3)
    )
    newer = _appointment_at(
        2, now, status=AppointmentStatus.EXPIRED, status_updated_at=now - timedelta(days=1)
    )
    other_status = _appointment_at(3, now, status=AppointmentStatus.PENDING)
    repo = FakeAppointmentRepository(page_items=[older, newer, other_status])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_client_appointments(123, "expired", 1)

    assert [a.id for a in result.items] == [2, 1]
    assert result.total_count == 2


@pytest.mark.asyncio
async def test_paginate_client_appointments_expired_tab_falls_back_to_created_at_when_status_updated_at_missing():
    now = get_current_tashkent_datetime()
    with_status_updated_at = _appointment_at(
        1, now, status=AppointmentStatus.EXPIRED, status_updated_at=now - timedelta(days=1)
    )
    without_status_updated_at = _appointment_at(
        2, now, status=AppointmentStatus.EXPIRED, created_at=now
    )
    repo = FakeAppointmentRepository(page_items=[with_status_updated_at, without_status_updated_at])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_client_appointments(123, "expired", 1)

    assert [a.id for a in result.items] == [2, 1]


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

    result = await service.paginate_client_appointments(123, "confirmed", 1)

    assert result.total_count == 0
    assert result.total_pages == 1
    assert result.current_page == 1
    assert result.items == []


@pytest.mark.asyncio
async def test_paginate_client_appointments_slices_across_page_boundary():
    now = get_current_tashkent_datetime()
    appointments = [
        _appointment_at(i, now + timedelta(days=i), status=AppointmentStatus.CONFIRMED)
        for i in range(1, APPOINTMENTS_PER_PAGE + 3)
    ]
    repo = FakeAppointmentRepository(page_items=appointments)
    service = AppointmentPaginationService(repo)

    page_1 = await service.paginate_client_appointments(123, "confirmed", 1)
    page_2 = await service.paginate_client_appointments(123, "confirmed", 2)

    assert len(page_1.items) == APPOINTMENTS_PER_PAGE
    assert len(page_2.items) == 2
    assert page_1.total_pages == 2
    assert [a.id for a in page_1.items] == list(range(1, APPOINTMENTS_PER_PAGE + 1))
    assert [a.id for a in page_2.items] == [APPOINTMENTS_PER_PAGE + 1, APPOINTMENTS_PER_PAGE + 2]


# --- paginate_active_client_appointments ---

@pytest.mark.asyncio
async def test_paginate_active_client_appointments_excludes_past_and_inactive_statuses():
    now = get_current_tashkent_datetime()
    future_pending = _appointment_at(1, now + timedelta(days=2), AppointmentStatus.PENDING)
    future_confirmed = _appointment_at(2, now + timedelta(days=1), AppointmentStatus.CONFIRMED)
    future_cancelled = _appointment_at(3, now + timedelta(days=1), AppointmentStatus.CANCELLED)
    past_pending = _appointment_at(4, now - timedelta(days=1), AppointmentStatus.PENDING)
    future_completed = _appointment_at(5, now + timedelta(days=1), AppointmentStatus.COMPLETED)
    repo = FakeAppointmentRepository(
        page_items=[future_pending, future_confirmed, future_cancelled, past_pending, future_completed]
    )
    service = AppointmentPaginationService(repo)

    result = await service.paginate_active_client_appointments(123, 1)

    assert [a.id for a in result.items] == [2, 1]
    assert result.total_count == 2


@pytest.mark.asyncio
async def test_paginate_active_client_appointments_sorted_soonest_first():
    now = get_current_tashkent_datetime()
    later = _appointment_at(1, now + timedelta(days=3), AppointmentStatus.PENDING)
    sooner = _appointment_at(2, now + timedelta(hours=1), AppointmentStatus.CONFIRMED)
    repo = FakeAppointmentRepository(page_items=[later, sooner])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_active_client_appointments(123, 1)

    assert [a.id for a in result.items] == [2, 1]


@pytest.mark.asyncio
async def test_paginate_active_client_appointments_empty_returns_single_page():
    repo = FakeAppointmentRepository(page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_active_client_appointments(123, 1)

    assert result.total_count == 0
    assert result.total_pages == 1
    assert result.items == []


@pytest.mark.asyncio
async def test_paginate_active_client_appointments_uses_proposed_datetime_when_present():
    now = get_current_tashkent_datetime()
    stale_datetime_but_future_proposal = _appointment_at(1, now - timedelta(days=1), AppointmentStatus.PENDING)
    stale_datetime_but_future_proposal.proposed_datetime = (now + timedelta(days=1)).isoformat()
    repo = FakeAppointmentRepository(page_items=[stale_datetime_but_future_proposal])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_active_client_appointments(123, 1)

    assert [a.id for a in result.items] == [1]
    assert result.total_count == 1


# --- paginate_all_appointments_by_tab ---
# NOTE: this method is backed by SQL-level pagination (see
# tests/test_appointment_repository.py for sort-order/COALESCE-fallback
# correctness against a real SQLite connection). These tests only verify
# routing: correct status resolved from tab, correct repository calls made,
# items passed through untouched, and pagination-math/error behaviour.

@pytest.mark.asyncio
async def test_paginate_all_appointments_by_tab_routes_resolved_status_to_repository():
    items = [_appointment(1), _appointment(2)]
    repo = FakeAppointmentRepository(total_count=2, page_items=items)
    service = AppointmentPaginationService(repo)

    result = await service.paginate_all_appointments_by_tab("confirmed", 1, clinic_id=1)

    assert result.items == items
    assert result.total_count == 2
    assert ("count_appointments_by_status", AppointmentStatus.CONFIRMED, 1, None, True) in repo.calls
    assert (
        "get_appointments_by_status_page",
        AppointmentStatus.CONFIRMED,
        1,
        1,
        None,
        APPOINTMENTS_PER_PAGE,
        True,
    ) in repo.calls


@pytest.mark.asyncio
async def test_paginate_all_appointments_by_tab_forwards_concrete_doctor_id_to_repository():
    repo = FakeAppointmentRepository(total_count=0, page_items=[])
    service = AppointmentPaginationService(repo)

    await service.paginate_all_appointments_by_tab("confirmed", 1, clinic_id=1, doctor_id=5)

    assert ("count_appointments_by_status", AppointmentStatus.CONFIRMED, 1, 5, True) in repo.calls
    assert (
        "get_appointments_by_status_page",
        AppointmentStatus.CONFIRMED,
        1,
        1,
        5,
        APPOINTMENTS_PER_PAGE,
        True,
    ) in repo.calls


@pytest.mark.asyncio
async def test_paginate_all_appointments_by_tab_forwards_tab_bucket_true_to_repository():
    """Only AppointmentPaginationService's tab-based methods pass tab_bucket=True --
    the safe default (False) is preserved for any other/future caller."""
    repo = FakeAppointmentRepository(total_count=0, page_items=[])
    service = AppointmentPaginationService(repo)

    await service.paginate_all_appointments_by_tab("confirmed", 1, clinic_id=1)

    status_calls = [call for call in repo.calls if call[0] == "count_appointments_by_status"]
    page_calls = [call for call in repo.calls if call[0] == "get_appointments_by_status_page"]
    assert status_calls and all(call[-1] is True for call in status_calls)
    assert page_calls and all(call[-1] is True for call in page_calls)


@pytest.mark.asyncio
async def test_paginate_all_appointments_by_tab_resolves_each_tab_to_its_status():
    repo = FakeAppointmentRepository(total_count=0, page_items=[])
    service = AppointmentPaginationService(repo)

    for tab, status in AppointmentPaginationService._STATUS_TABS.items():
        repo.calls.clear()
        await service.paginate_all_appointments_by_tab(tab, 1, clinic_id=1)
        assert ("count_appointments_by_status", status, 1, None, True) in repo.calls


@pytest.mark.asyncio
async def test_paginate_all_appointments_by_tab_unknown_tab_raises_pagination_error():
    repo = FakeAppointmentRepository(page_items=[])
    service = AppointmentPaginationService(repo)

    with pytest.raises(PaginationError):
        await service.paginate_all_appointments_by_tab("unknown", 1, clinic_id=1)


@pytest.mark.asyncio
async def test_paginate_all_appointments_by_tab_unknown_tab_does_not_touch_repository():
    repo = FakeAppointmentRepository(page_items=[])
    service = AppointmentPaginationService(repo)

    with pytest.raises(PaginationError):
        await service.paginate_all_appointments_by_tab("unknown", 1, clinic_id=1)

    assert repo.calls == []


@pytest.mark.asyncio
async def test_paginate_all_appointments_by_tab_total_pages_computed_with_ceil():
    repo = FakeAppointmentRepository(total_count=21, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_all_appointments_by_tab("confirmed", 1, clinic_id=1)

    assert result.total_pages == 3  # ceil(21 / 10)


@pytest.mark.asyncio
async def test_paginate_all_appointments_by_tab_clamps_page_before_querying_repository():
    repo = FakeAppointmentRepository(total_count=15, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_all_appointments_by_tab("confirmed", 999, clinic_id=1)

    assert result.total_pages == 2  # ceil(15 / 10)
    assert result.current_page == 2
    assert (
        "get_appointments_by_status_page",
        AppointmentStatus.CONFIRMED,
        2,
        1,
        None,
        APPOINTMENTS_PER_PAGE,
        True,
    ) in repo.calls


@pytest.mark.asyncio
async def test_paginate_all_appointments_by_tab_empty_result_returns_single_page():
    repo = FakeAppointmentRepository(page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_all_appointments_by_tab("confirmed", 1, clinic_id=1)

    assert result.total_count == 0
    assert result.total_pages == 1
    assert result.current_page == 1
    assert result.items == []


# --- paginate_appointments_by_date_and_tab ---
# NOTE: mirrors paginate_all_appointments_by_tab's tests (see the note above
# that block) - SQL-level pagination, so these only verify routing.

@pytest.mark.asyncio
async def test_paginate_appointments_by_date_and_tab_routes_date_and_resolved_status_to_repository():
    items = [_appointment(1), _appointment(2)]
    repo = FakeAppointmentRepository(total_count=2, page_items=items)
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments_by_date_and_tab("2026-07-10", "confirmed", 1, clinic_id=1)

    assert result.items == items
    assert result.total_count == 2
    assert (
        "count_appointments_by_date_and_status", "2026-07-10", AppointmentStatus.CONFIRMED, 1, None, True
    ) in repo.calls
    assert (
        "get_appointments_by_date_and_status_page",
        "2026-07-10",
        AppointmentStatus.CONFIRMED,
        1,
        1,
        None,
        APPOINTMENTS_PER_PAGE,
        True,
    ) in repo.calls


@pytest.mark.asyncio
async def test_paginate_appointments_by_date_and_tab_forwards_concrete_doctor_id_to_repository():
    repo = FakeAppointmentRepository(total_count=0, page_items=[])
    service = AppointmentPaginationService(repo)

    await service.paginate_appointments_by_date_and_tab("2026-07-10", "confirmed", 1, clinic_id=1, doctor_id=5)

    assert (
        "count_appointments_by_date_and_status", "2026-07-10", AppointmentStatus.CONFIRMED, 1, 5, True
    ) in repo.calls
    assert (
        "get_appointments_by_date_and_status_page",
        "2026-07-10",
        AppointmentStatus.CONFIRMED,
        1,
        1,
        5,
        APPOINTMENTS_PER_PAGE,
        True,
    ) in repo.calls


@pytest.mark.asyncio
async def test_paginate_appointments_by_date_and_tab_forwards_tab_bucket_true_to_repository():
    """Only AppointmentPaginationService's tab-based methods pass tab_bucket=True --
    the safe default (False) is preserved for any other/future caller."""
    repo = FakeAppointmentRepository(total_count=0, page_items=[])
    service = AppointmentPaginationService(repo)

    await service.paginate_appointments_by_date_and_tab("2026-07-10", "confirmed", 1, clinic_id=1)

    status_calls = [call for call in repo.calls if call[0] == "count_appointments_by_date_and_status"]
    page_calls = [call for call in repo.calls if call[0] == "get_appointments_by_date_and_status_page"]
    assert status_calls and all(call[-1] is True for call in status_calls)
    assert page_calls and all(call[-1] is True for call in page_calls)


@pytest.mark.asyncio
async def test_paginate_appointments_by_date_and_tab_resolves_each_tab_to_its_status():
    repo = FakeAppointmentRepository(total_count=0, page_items=[])
    service = AppointmentPaginationService(repo)

    for tab, status in AppointmentPaginationService._STATUS_TABS.items():
        repo.calls.clear()
        await service.paginate_appointments_by_date_and_tab("2026-07-10", tab, 1, clinic_id=1)
        assert ("count_appointments_by_date_and_status", "2026-07-10", status, 1, None, True) in repo.calls


@pytest.mark.asyncio
async def test_paginate_appointments_by_date_and_tab_unknown_tab_raises_pagination_error():
    repo = FakeAppointmentRepository(page_items=[])
    service = AppointmentPaginationService(repo)

    with pytest.raises(PaginationError):
        await service.paginate_appointments_by_date_and_tab("2026-07-10", "unknown", 1, clinic_id=1)


@pytest.mark.asyncio
async def test_paginate_appointments_by_date_and_tab_unknown_tab_does_not_touch_repository():
    repo = FakeAppointmentRepository(page_items=[])
    service = AppointmentPaginationService(repo)

    with pytest.raises(PaginationError):
        await service.paginate_appointments_by_date_and_tab("2026-07-10", "unknown", 1, clinic_id=1)

    assert repo.calls == []


@pytest.mark.asyncio
async def test_paginate_appointments_by_date_and_tab_total_pages_computed_with_ceil():
    repo = FakeAppointmentRepository(total_count=21, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments_by_date_and_tab("2026-07-10", "confirmed", 1, clinic_id=1)

    assert result.total_pages == 3  # ceil(21 / 10)


@pytest.mark.asyncio
async def test_paginate_appointments_by_date_and_tab_clamps_page_before_querying_repository():
    repo = FakeAppointmentRepository(total_count=15, page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments_by_date_and_tab("2026-07-10", "confirmed", 999, clinic_id=1)

    assert result.total_pages == 2  # ceil(15 / 10)
    assert result.current_page == 2
    assert (
        "get_appointments_by_date_and_status_page",
        "2026-07-10",
        AppointmentStatus.CONFIRMED,
        2,
        1,
        None,
        APPOINTMENTS_PER_PAGE,
        True,
    ) in repo.calls


@pytest.mark.asyncio
async def test_paginate_appointments_by_date_and_tab_empty_result_returns_single_page():
    repo = FakeAppointmentRepository(page_items=[])
    service = AppointmentPaginationService(repo)

    result = await service.paginate_appointments_by_date_and_tab("2026-07-10", "confirmed", 1, clinic_id=1)

    assert result.total_count == 0
    assert result.total_pages == 1
    assert result.current_page == 1
    assert result.items == []
