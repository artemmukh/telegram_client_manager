import dataclasses

import aiosqlite
import pytest
import pytest_asyncio

from bot.exceptions.appointment_exceptions import SlotUnavailableError
from bot.models.appointment import Appointment
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.staff_repository import StaffRepository
from bot.repositories.user_repository import UserRepository
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


@pytest_asyncio.fixture
async def appointment_setup(tmp_path):
    connection = await aiosqlite.connect(tmp_path / "test.db")
    await connection.execute("PRAGMA foreign_keys = ON")

    clinic_repo = ClinicRepository(connection)
    user_repo = UserRepository(connection)
    staff_repo = StaffRepository(connection)
    appointment_repo = AppointmentRepository(connection)

    await clinic_repo.init()
    await user_repo.init()
    await staff_repo.init()
    await appointment_repo.init()

    await user_repo.create_user(
        User(
            full_name="Иванов Иван",
            phone="+998901234567",
            role=Role.CLIENT,
            telegram_user_id=1001,
        )
    )
    user = await user_repo.get_user_by_telegram_id(1001)

    yield appointment_repo, user

    await connection.close()


def _appointment(client_id: int) -> Appointment:
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        datetime="2026-07-01 10:00",
        purpose="Consultation",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
    )


@pytest.mark.asyncio
async def test_creates_and_reads_appointment(appointment_setup):
    appointment_repo, user = appointment_setup

    await appointment_repo.create_appointment(_appointment(user.ID))

    by_client = await appointment_repo.get_appointments_by_client_id(user.ID, clinic_id=1)
    by_telegram = await appointment_repo.get_appointments_by_telegram_id(1001)
    by_id = await appointment_repo.get_appointment_by_id(by_client[0].id)

    assert len(by_client) == 1
    assert by_client[0].purpose == "Consultation"
    assert by_client[0].status is AppointmentStatus.PENDING
    assert by_client[0].created_by is CreatedBy.ADMIN
    assert by_telegram == by_client
    assert by_id == by_client[0]
    assert await appointment_repo.appointment_exists(by_client[0].id) is True


@pytest.mark.asyncio
async def test_updates_appointment_status(appointment_setup):
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID, clinic_id=1))[0].id

    await appointment_repo.update_appointment_status(
        appointment_id, AppointmentStatus.CONFIRMED, "2026-07-02 10:00:00"
    )

    updated = await appointment_repo.get_appointment_by_id(appointment_id)
    assert updated.status is AppointmentStatus.CONFIRMED
    assert updated.status_updated_at == "2026-07-02 10:00:00"


@pytest.mark.asyncio
async def test_deletes_appointment(appointment_setup):
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID, clinic_id=1))[0].id

    await appointment_repo.delete_appointment(appointment_id)

    assert await appointment_repo.get_appointment_by_id(appointment_id) is None
    assert await appointment_repo.appointment_exists(appointment_id) is False


# --- Pagination methods (in-memory sqlite, to avoid Windows file-lock flakiness) ---

async def _in_memory_repos():
    connection = await aiosqlite.connect(":memory:")
    clinic_repo = ClinicRepository(connection)
    user_repo = UserRepository(connection)
    staff_repo = StaffRepository(connection)
    appointment_repo = AppointmentRepository(connection)

    await clinic_repo.init()
    await user_repo.init()
    await staff_repo.init()
    await appointment_repo.init()

    return connection, user_repo, appointment_repo


async def _seed_client(user_repo: UserRepository, full_name: str, phone: str) -> User:
    await user_repo.create_user(
        User(full_name=full_name, phone=phone, role=Role.CLIENT)
    )
    return await user_repo.get_client_by_phone(phone)


def _appointment_for(client_id: int, created_at: str) -> Appointment:
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        datetime="2026-07-01 10:00",
        purpose="Consultation",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_get_appointments_page_paginates_with_correct_offset_and_ordering():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")

        for i in range(1, 6):
            await appointment_repo.create_appointment(
                _appointment_for(client.ID, created_at=f"2026-07-0{i} 10:00:00")
            )

        assert await appointment_repo.count_appointments(clinic_id=1) == 5

        page_one = await appointment_repo.get_appointments_page(1, clinic_id=1, per_page=2)
        page_two = await appointment_repo.get_appointments_page(2, clinic_id=1, per_page=2)
        page_three = await appointment_repo.get_appointments_page(3, clinic_id=1, per_page=2)

        # Newest created_at first (DESC), page 1 = offset 0.
        assert [a.created_at for a in page_one] == ["2026-07-05 10:00:00", "2026-07-04 10:00:00"]
        assert [a.created_at for a in page_two] == ["2026-07-03 10:00:00", "2026-07-02 10:00:00"]
        assert [a.created_at for a in page_three] == ["2026-07-01 10:00:00"]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_name_and_status_page_matches_multi_token_full_name():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        ivanov = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        petrov = await _seed_client(user_repo, "Петров Пётр", "+998902222222")
        sidorov = await _seed_client(user_repo, "Сидоров Семён", "+998903333333")

        await appointment_repo.create_appointment(_appointment_for(ivanov.ID, "2026-07-01 10:00:00"))
        await appointment_repo.create_appointment(_appointment_for(petrov.ID, "2026-07-02 10:00:00"))
        await appointment_repo.create_appointment(_appointment_for(sidorov.ID, "2026-07-03 10:00:00"))

        # Multi-token search matches either token (OR), so both "Иванов" and "Пётр" match.
        count = await appointment_repo.count_appointments_by_name_and_status(
            "Иванов Пётр", AppointmentStatus.PENDING, clinic_id=1
        )
        page = await appointment_repo.get_appointments_by_name_and_status_page(
            "Иванов Пётр", AppointmentStatus.PENDING, 1, clinic_id=1, per_page=10
        )

        assert count == 2
        assert count == len(page)
        assert {a.client_id for a in page} == {ivanov.ID, petrov.ID}
        assert sidorov.ID not in {a.client_id for a in page}
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_name_and_status_page_normalizes_case_before_matching():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        ivanov = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        await appointment_repo.create_appointment(_appointment_for(ivanov.ID, "2026-07-01 10:00:00"))

        # Input is lower-cased; repository .title()-normalizes it before LIKE.
        count = await appointment_repo.count_appointments_by_name_and_status(
            "иванов", AppointmentStatus.PENDING, clinic_id=1
        )
        page = await appointment_repo.get_appointments_by_name_and_status_page(
            "иванов", AppointmentStatus.PENDING, 1, clinic_id=1, per_page=10
        )

        assert count == 1
        assert len(page) == 1
        assert page[0].client_id == ivanov.ID
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_name_and_status_page_empty_full_name_is_defensive_guard():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        await appointment_repo.create_appointment(_appointment_for(client.ID, "2026-07-01 10:00:00"))

        assert await appointment_repo.get_appointments_by_name_and_status_page(
            "", AppointmentStatus.PENDING, 1, clinic_id=1, per_page=10
        ) == []
        assert await appointment_repo.count_appointments_by_name_and_status(
            "", AppointmentStatus.PENDING, clinic_id=1
        ) == 0

        # Whitespace-only input also strips down to an empty token list.
        assert await appointment_repo.get_appointments_by_name_and_status_page(
            "   ", AppointmentStatus.PENDING, 1, clinic_id=1, per_page=10
        ) == []
        assert await appointment_repo.count_appointments_by_name_and_status(
            "   ", AppointmentStatus.PENDING, clinic_id=1
        ) == 0
    finally:
        await connection.close()


# --- tab_bucket + sort order: get_appointments_by_name_and_status_page / count_appointments_by_name_and_status ---

@pytest.mark.asyncio
async def test_get_appointments_by_name_and_status_page_tab_bucket_false_keeps_negotiating_appointment_under_confirmed():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        negotiating = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 10:00:00", AppointmentStatus.CONFIRMED, "2026-07-01 10:00:00")
        )
        await appointment_repo.update_proposed_datetime(negotiating.id, "2026-08-01 10:00:00")

        confirmed_page = await appointment_repo.get_appointments_by_name_and_status_page(
            "Иванов", AppointmentStatus.CONFIRMED, 1, clinic_id=1, per_page=10
        )
        pending_page = await appointment_repo.get_appointments_by_name_and_status_page(
            "Иванов", AppointmentStatus.PENDING, 1, clinic_id=1, per_page=10
        )
        confirmed_count = await appointment_repo.count_appointments_by_name_and_status(
            "Иванов", AppointmentStatus.CONFIRMED, clinic_id=1
        )
        pending_count = await appointment_repo.count_appointments_by_name_and_status(
            "Иванов", AppointmentStatus.PENDING, clinic_id=1
        )

        assert [a.id for a in confirmed_page] == [negotiating.id]
        assert pending_page == []
        assert confirmed_count == 1
        assert pending_count == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_name_and_status_page_tab_bucket_true_moves_negotiating_appointment_to_pending():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        negotiating = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 10:00:00", AppointmentStatus.CONFIRMED, "2026-07-01 10:00:00")
        )
        await appointment_repo.update_proposed_datetime(negotiating.id, "2026-08-01 10:00:00")
        plain_confirmed = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-11 10:00:00", AppointmentStatus.CONFIRMED, "2026-07-02 10:00:00")
        )
        plain_pending = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-12 10:00:00", AppointmentStatus.PENDING, "2026-07-03 10:00:00")
        )

        confirmed_page = await appointment_repo.get_appointments_by_name_and_status_page(
            "Иванов", AppointmentStatus.CONFIRMED, 1, clinic_id=1, per_page=10, tab_bucket=True
        )
        pending_page = await appointment_repo.get_appointments_by_name_and_status_page(
            "Иванов", AppointmentStatus.PENDING, 1, clinic_id=1, per_page=10, tab_bucket=True
        )
        confirmed_count = await appointment_repo.count_appointments_by_name_and_status(
            "Иванов", AppointmentStatus.CONFIRMED, clinic_id=1, tab_bucket=True
        )
        pending_count = await appointment_repo.count_appointments_by_name_and_status(
            "Иванов", AppointmentStatus.PENDING, clinic_id=1, tab_bucket=True
        )

        assert [a.id for a in confirmed_page] == [plain_confirmed.id]
        assert {a.id for a in pending_page} == {negotiating.id, plain_pending.id}
        assert confirmed_count == 1
        assert pending_count == 2
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_name_and_status_page_uses_status_appropriate_sort_order():
    """Verifies get_appointments_by_name_and_status_page sorts via _status_order_by
    (created_at DESC for the pending bucket), not a fixed/insertion order."""
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")

        older = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 10:00:00", AppointmentStatus.PENDING, "2026-07-01 10:00:00")
        )
        newer = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-11 10:00:00", AppointmentStatus.PENDING, "2026-07-02 10:00:00")
        )

        page = await appointment_repo.get_appointments_by_name_and_status_page(
            "Иванов", AppointmentStatus.PENDING, 1, clinic_id=1, per_page=10
        )

        assert [a.id for a in page] == [newer.id, older.id]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_client_id_page_paginates_single_client_appointments():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        target = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        other = await _seed_client(user_repo, "Петров Пётр", "+998902222222")

        for i in range(1, 4):
            await appointment_repo.create_appointment(
                _appointment_for(target.ID, created_at=f"2026-07-0{i} 10:00:00")
            )
        await appointment_repo.create_appointment(_appointment_for(other.ID, "2026-07-04 10:00:00"))

        total_count = await appointment_repo.count_appointments_by_client_id(target.ID, clinic_id=1)
        page_one = await appointment_repo.get_appointments_by_client_id_page(target.ID, 1, clinic_id=1, per_page=2)
        page_two = await appointment_repo.get_appointments_by_client_id_page(target.ID, 2, clinic_id=1, per_page=2)

        assert total_count == 3
        assert all(a.client_id == target.ID for a in page_one + page_two)
        assert [a.created_at for a in page_one] == ["2026-07-03 10:00:00", "2026-07-02 10:00:00"]
        assert [a.created_at for a in page_two] == ["2026-07-01 10:00:00"]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_count_and_page_results_stay_consistent_for_client_id():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        assert await appointment_repo.count_appointments_by_client_id(client.ID, clinic_id=1) == 0
        assert await appointment_repo.get_appointments_by_client_id_page(client.ID, 1, clinic_id=1, per_page=10) == []

        await appointment_repo.create_appointment(_appointment_for(client.ID, "2026-07-01 10:00:00"))

        count = await appointment_repo.count_appointments_by_client_id(client.ID, clinic_id=1)
        page = await appointment_repo.get_appointments_by_client_id_page(client.ID, 1, clinic_id=1, per_page=10)

        assert count == len(page) == 1
    finally:
        await connection.close()


def _appointment_with_status(
    client_id: int,
    dt: str,
    status: AppointmentStatus,
    created_at: str,
    status_updated_at: str | None = None,
) -> Appointment:
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        datetime=dt,
        purpose="Consultation",
        created_by=CreatedBy.ADMIN,
        status=status,
        created_at=created_at,
        status_updated_at=status_updated_at,
    )


@pytest.mark.asyncio
async def test_get_appointments_by_status_page_confirmed_sorted_soonest_first_with_id_tiebreak():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")

        same_time = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 10:00:00", AppointmentStatus.CONFIRMED, "2026-07-01 10:00:00")
        )
        await appointment_repo.update_appointment_status(same_time.id, AppointmentStatus.CONFIRMED, "2026-07-01 10:00:00")

        second_same_time = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 10:00:00", AppointmentStatus.CONFIRMED, "2026-07-02 10:00:00")
        )
        sooner = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-05 10:00:00", AppointmentStatus.CONFIRMED, "2026-07-03 10:00:00")
        )
        await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-01 10:00:00", AppointmentStatus.PENDING, "2026-07-04 10:00:00")
        )

        count = await appointment_repo.count_appointments_by_status(AppointmentStatus.CONFIRMED, clinic_id=1)
        page = await appointment_repo.get_appointments_by_status_page(
            AppointmentStatus.CONFIRMED, 1, clinic_id=1, per_page=10
        )

        assert count == 3
        assert [a.id for a in page] == [sooner.id, same_time.id, second_same_time.id]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_status_page_pending_sorted_by_created_at_desc():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")

        older = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-01 10:00:00", AppointmentStatus.PENDING, "2026-07-01 10:00:00")
        )
        newer = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-01 10:00:00", AppointmentStatus.PENDING, "2026-07-02 10:00:00")
        )
        await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-01 10:00:00", AppointmentStatus.CONFIRMED, "2026-07-03 10:00:00")
        )

        count = await appointment_repo.count_appointments_by_status(AppointmentStatus.PENDING, clinic_id=1)
        page = await appointment_repo.get_appointments_by_status_page(
            AppointmentStatus.PENDING, 1, clinic_id=1, per_page=10
        )

        assert count == 2
        assert [a.id for a in page] == [newer.id, older.id]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_status_page_cancelled_sorted_by_status_updated_at_desc_with_fallback():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")

        with_status_updated_at = await appointment_repo.create_appointment(
            _appointment_with_status(
                client.ID, "2026-07-01 10:00:00", AppointmentStatus.CANCELLED, "2026-07-01 10:00:00"
            )
        )
        await appointment_repo.update_appointment_status(
            with_status_updated_at.id, AppointmentStatus.CANCELLED, "2026-07-05 10:00:00"
        )

        fallback_to_created_at = await appointment_repo.create_appointment(
            _appointment_with_status(
                client.ID, "2026-07-01 10:00:00", AppointmentStatus.CANCELLED, "2026-07-10 10:00:00"
            )
        )
        await connection.execute(
            "UPDATE appointments SET status_updated_at = NULL WHERE id = ?",
            (fallback_to_created_at.id,),
        )
        await connection.commit()

        page = await appointment_repo.get_appointments_by_status_page(
            AppointmentStatus.CANCELLED, 1, clinic_id=1, per_page=10
        )

        # fallback_to_created_at has NULL status_updated_at, so COALESCE falls back
        # to its created_at (2026-07-10), which should sort ahead of 2026-07-05.
        assert [a.id for a in page] == [fallback_to_created_at.id, with_status_updated_at.id]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_status_page_paginates_with_offset():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")

        for i in range(1, 4):
            await appointment_repo.create_appointment(
                _appointment_with_status(
                    client.ID, "2026-07-01 10:00:00", AppointmentStatus.PENDING, f"2026-07-0{i} 10:00:00"
                )
            )

        page_one = await appointment_repo.get_appointments_by_status_page(
            AppointmentStatus.PENDING, 1, clinic_id=1, per_page=2
        )
        page_two = await appointment_repo.get_appointments_by_status_page(
            AppointmentStatus.PENDING, 2, clinic_id=1, per_page=2
        )

        assert [a.created_at for a in page_one] == ["2026-07-03 10:00:00", "2026-07-02 10:00:00"]
        assert [a.created_at for a in page_two] == ["2026-07-01 10:00:00"]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_count_appointments_by_status_returns_zero_when_no_matches():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-01 10:00:00", AppointmentStatus.PENDING, "2026-07-01 10:00:00")
        )

        assert await appointment_repo.count_appointments_by_status(AppointmentStatus.CONFIRMED, clinic_id=1) == 0
    finally:
        await connection.close()


# --- tab_bucket: CONFIRMED+proposed_datetime reclassified into the pending bucket ---

@pytest.mark.asyncio
async def test_get_appointments_by_status_page_tab_bucket_false_keeps_negotiating_appointment_under_confirmed():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        negotiating = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 10:00:00", AppointmentStatus.CONFIRMED, "2026-07-01 10:00:00")
        )
        await appointment_repo.update_proposed_datetime(negotiating.id, "2026-08-01 10:00:00")

        confirmed_page = await appointment_repo.get_appointments_by_status_page(
            AppointmentStatus.CONFIRMED, 1, clinic_id=1, per_page=10
        )
        pending_page = await appointment_repo.get_appointments_by_status_page(
            AppointmentStatus.PENDING, 1, clinic_id=1, per_page=10
        )
        confirmed_count = await appointment_repo.count_appointments_by_status(AppointmentStatus.CONFIRMED, clinic_id=1)
        pending_count = await appointment_repo.count_appointments_by_status(AppointmentStatus.PENDING, clinic_id=1)

        assert [a.id for a in confirmed_page] == [negotiating.id]
        assert pending_page == []
        assert confirmed_count == 1
        assert pending_count == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_status_page_tab_bucket_true_moves_negotiating_appointment_to_pending():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        negotiating = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 10:00:00", AppointmentStatus.CONFIRMED, "2026-07-01 10:00:00")
        )
        await appointment_repo.update_proposed_datetime(negotiating.id, "2026-08-01 10:00:00")
        plain_confirmed = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-11 10:00:00", AppointmentStatus.CONFIRMED, "2026-07-02 10:00:00")
        )
        plain_pending = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-12 10:00:00", AppointmentStatus.PENDING, "2026-07-03 10:00:00")
        )

        confirmed_page = await appointment_repo.get_appointments_by_status_page(
            AppointmentStatus.CONFIRMED, 1, clinic_id=1, per_page=10, tab_bucket=True
        )
        pending_page = await appointment_repo.get_appointments_by_status_page(
            AppointmentStatus.PENDING, 1, clinic_id=1, per_page=10, tab_bucket=True
        )
        confirmed_count = await appointment_repo.count_appointments_by_status(
            AppointmentStatus.CONFIRMED, clinic_id=1, tab_bucket=True
        )
        pending_count = await appointment_repo.count_appointments_by_status(
            AppointmentStatus.PENDING, clinic_id=1, tab_bucket=True
        )

        assert [a.id for a in confirmed_page] == [plain_confirmed.id]
        assert {a.id for a in pending_page} == {negotiating.id, plain_pending.id}
        assert confirmed_count == 1
        assert pending_count == 2
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_date_and_status_page_tab_bucket_true_moves_negotiating_appointment_to_pending():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        negotiating = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 10:00:00", AppointmentStatus.CONFIRMED, "2026-07-01 10:00:00")
        )
        await appointment_repo.update_proposed_datetime(negotiating.id, "2026-08-01 10:00:00")
        plain_confirmed = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 11:00:00", AppointmentStatus.CONFIRMED, "2026-07-02 10:00:00")
        )
        plain_pending = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 12:00:00", AppointmentStatus.PENDING, "2026-07-03 10:00:00")
        )

        confirmed_page = await appointment_repo.get_appointments_by_date_and_status_page(
            "2026-07-10", AppointmentStatus.CONFIRMED, 1, clinic_id=1, per_page=10, tab_bucket=True
        )
        pending_page = await appointment_repo.get_appointments_by_date_and_status_page(
            "2026-07-10", AppointmentStatus.PENDING, 1, clinic_id=1, per_page=10, tab_bucket=True
        )
        confirmed_count = await appointment_repo.count_appointments_by_date_and_status(
            "2026-07-10", AppointmentStatus.CONFIRMED, clinic_id=1, tab_bucket=True
        )
        pending_count = await appointment_repo.count_appointments_by_date_and_status(
            "2026-07-10", AppointmentStatus.PENDING, clinic_id=1, tab_bucket=True
        )

        assert [a.id for a in confirmed_page] == [plain_confirmed.id]
        assert {a.id for a in pending_page} == {negotiating.id, plain_pending.id}
        assert confirmed_count == 1
        assert pending_count == 2
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_date_and_status_page_tab_bucket_false_keeps_negotiating_appointment_under_confirmed():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        negotiating = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 10:00:00", AppointmentStatus.CONFIRMED, "2026-07-01 10:00:00")
        )
        await appointment_repo.update_proposed_datetime(negotiating.id, "2026-08-01 10:00:00")

        confirmed_page = await appointment_repo.get_appointments_by_date_and_status_page(
            "2026-07-10", AppointmentStatus.CONFIRMED, 1, clinic_id=1, per_page=10
        )
        pending_page = await appointment_repo.get_appointments_by_date_and_status_page(
            "2026-07-10", AppointmentStatus.PENDING, 1, clinic_id=1, per_page=10
        )
        confirmed_count = await appointment_repo.count_appointments_by_date_and_status(
            "2026-07-10", AppointmentStatus.CONFIRMED, clinic_id=1
        )
        pending_count = await appointment_repo.count_appointments_by_date_and_status(
            "2026-07-10", AppointmentStatus.PENDING, clinic_id=1
        )

        assert [a.id for a in confirmed_page] == [negotiating.id]
        assert pending_page == []
        assert confirmed_count == 1
        assert pending_count == 0
    finally:
        await connection.close()


# --- Calendar: date + status filtering (appt_search_calendar feature) ---

@pytest.mark.asyncio
async def test_get_appointments_by_date_and_status_page_filters_exact_day_sorted_by_datetime_asc():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")

        matching_later = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 15:00:00", AppointmentStatus.CONFIRMED, "2026-07-01 10:00:00")
        )
        matching_earlier = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 09:00:00", AppointmentStatus.CONFIRMED, "2026-07-02 10:00:00")
        )
        # Different day, same status - must be excluded.
        await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-11 09:00:00", AppointmentStatus.CONFIRMED, "2026-07-03 10:00:00")
        )
        # Same day, different status - must be excluded.
        await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 12:00:00", AppointmentStatus.PENDING, "2026-07-04 10:00:00")
        )

        count = await appointment_repo.count_appointments_by_date_and_status(
            "2026-07-10", AppointmentStatus.CONFIRMED, clinic_id=1
        )
        page = await appointment_repo.get_appointments_by_date_and_status_page(
            "2026-07-10", AppointmentStatus.CONFIRMED, 1, clinic_id=1, per_page=10
        )

        assert count == 2
        assert [a.id for a in page] == [matching_earlier.id, matching_later.id]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_date_and_status_page_respects_clinic_and_doctor_scope():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")

        own_doctor = await appointment_repo.create_appointment(
            Appointment(
                clinic_id=1, client_id=client.ID, doctor_id=100,
                datetime="2026-07-10 10:00", purpose="Consultation",
                created_by=CreatedBy.ADMIN, status=AppointmentStatus.CONFIRMED,
            )
        )
        await appointment_repo.create_appointment(
            Appointment(
                clinic_id=1, client_id=client.ID, doctor_id=200,
                datetime="2026-07-10 11:00", purpose="Consultation",
                created_by=CreatedBy.ADMIN, status=AppointmentStatus.CONFIRMED,
            )
        )
        await appointment_repo.create_appointment(
            Appointment(
                clinic_id=2, client_id=client.ID, doctor_id=100,
                datetime="2026-07-10 12:00", purpose="Consultation",
                created_by=CreatedBy.ADMIN, status=AppointmentStatus.CONFIRMED,
            )
        )

        by_doctor = await appointment_repo.get_appointments_by_date_and_status_page(
            "2026-07-10", AppointmentStatus.CONFIRMED, 1, clinic_id=1, doctor_id=100, per_page=10
        )
        assert [a.id for a in by_doctor] == [own_doctor.id]
        assert await appointment_repo.count_appointments_by_date_and_status(
            "2026-07-10", AppointmentStatus.CONFIRMED, clinic_id=1, doctor_id=100
        ) == 1

        clinic_wide = await appointment_repo.get_appointments_by_date_and_status_page(
            "2026-07-10", AppointmentStatus.CONFIRMED, 1, clinic_id=1, per_page=10
        )
        assert len(clinic_wide) == 2
        assert await appointment_repo.count_appointments_by_date_and_status(
            "2026-07-10", AppointmentStatus.CONFIRMED, clinic_id=1
        ) == 2
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_date_and_status_page_paginates_with_offset():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")

        for hour in range(9, 12):
            await appointment_repo.create_appointment(
                _appointment_with_status(
                    client.ID, f"2026-07-10 {hour:02d}:00:00", AppointmentStatus.CONFIRMED, "2026-07-01 10:00:00"
                )
            )

        page_one = await appointment_repo.get_appointments_by_date_and_status_page(
            "2026-07-10", AppointmentStatus.CONFIRMED, 1, clinic_id=1, per_page=2
        )
        page_two = await appointment_repo.get_appointments_by_date_and_status_page(
            "2026-07-10", AppointmentStatus.CONFIRMED, 2, clinic_id=1, per_page=2
        )

        assert [a.datetime for a in page_one] == ["2026-07-10 09:00:00", "2026-07-10 10:00:00"]
        assert [a.datetime for a in page_two] == ["2026-07-10 11:00:00"]
    finally:
        await connection.close()


# --- Visibility scope: clinic_id/doctor_id filtering (admin_visibility_scope feature) ---

@pytest.mark.asyncio
async def test_clinic_and_doctor_filters_exclude_other_clinics_and_other_doctors():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        await connection.execute(
            "INSERT INTO clinics (id, name, token) VALUES (2, 'Клиника 2', 'tok2')"
        )
        await connection.commit()

        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")

        own_doctor = await appointment_repo.create_appointment(
            Appointment(
                clinic_id=1, client_id=client.ID, doctor_id=100,
                datetime="2026-07-01 10:00", purpose="Consultation",
                created_by=CreatedBy.ADMIN, status=AppointmentStatus.PENDING,
            )
        )
        other_doctor = await appointment_repo.create_appointment(
            Appointment(
                clinic_id=1, client_id=client.ID, doctor_id=200,
                datetime="2026-07-02 10:00", purpose="Consultation",
                created_by=CreatedBy.ADMIN, status=AppointmentStatus.PENDING,
            )
        )
        other_clinic = await appointment_repo.create_appointment(
            Appointment(
                clinic_id=2, client_id=client.ID, doctor_id=100,
                datetime="2026-07-03 10:00", purpose="Consultation",
                created_by=CreatedBy.ADMIN, status=AppointmentStatus.PENDING,
            )
        )

        own_only = await appointment_repo.get_appointments_page(1, clinic_id=1, doctor_id=100, per_page=10)
        assert [a.id for a in own_only] == [own_doctor.id]
        assert await appointment_repo.count_appointments(clinic_id=1, doctor_id=100) == 1

        clinic_wide = await appointment_repo.get_appointments_page(1, clinic_id=1, per_page=10)
        assert {a.id for a in clinic_wide} == {own_doctor.id, other_doctor.id}
        assert await appointment_repo.count_appointments(clinic_id=1) == 2

        assert other_clinic.id not in {a.id for a in clinic_wide}
        assert await appointment_repo.count_appointments(clinic_id=2) == 1

        by_status = await appointment_repo.get_appointments_by_status_page(
            AppointmentStatus.PENDING, 1, clinic_id=1, doctor_id=100, per_page=10
        )
        assert [a.id for a in by_status] == [own_doctor.id]
        assert await appointment_repo.count_appointments_by_status(
            AppointmentStatus.PENDING, clinic_id=1, doctor_id=100
        ) == 1

        by_name = await appointment_repo.get_appointments_by_name_and_status_page(
            "Иванов", AppointmentStatus.PENDING, 1, clinic_id=1, doctor_id=100, per_page=10
        )
        assert [a.id for a in by_name] == [own_doctor.id]

        by_client = await appointment_repo.get_appointments_by_client_id(client.ID, clinic_id=1, doctor_id=100)
        assert [a.id for a in by_client] == [own_doctor.id]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_update_proposed_datetime_round_trips_via_get_by_id_and_by_telegram_id():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        await user_repo.create_user(
            User(full_name="Иванов Иван", phone="+998901111111", role=Role.CLIENT, telegram_user_id=2001)
        )
        client = await user_repo.get_user_by_telegram_id(2001)

        created = await appointment_repo.create_appointment(_appointment_for(client.ID, "2026-07-01 10:00:00"))
        assert created.proposed_datetime is None

        await appointment_repo.update_proposed_datetime(created.id, "2026-07-05 15:00")

        by_id = await appointment_repo.get_appointment_by_id(created.id)
        by_telegram = await appointment_repo.get_appointments_by_telegram_id(2001)

        assert by_id.proposed_datetime == "2026-07-05 15:00"
        assert by_telegram[0].proposed_datetime == "2026-07-05 15:00"

        await appointment_repo.update_proposed_datetime(created.id, None)

        by_id_cleared = await appointment_repo.get_appointment_by_id(created.id)
        by_telegram_cleared = await appointment_repo.get_appointments_by_telegram_id(2001)

        assert by_id_cleared.proposed_datetime is None
        assert by_telegram_cleared[0].proposed_datetime is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_update_proposal_message_id_round_trips_via_get_by_id_and_by_telegram_id():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        await user_repo.create_user(
            User(full_name="Иванов Иван", phone="+998901111111", role=Role.CLIENT, telegram_user_id=2002)
        )
        client = await user_repo.get_user_by_telegram_id(2002)

        created = await appointment_repo.create_appointment(_appointment_for(client.ID, "2026-07-01 10:00:00"))
        assert created.proposal_message_id is None

        await appointment_repo.update_proposal_message_id(created.id, 999)

        by_id = await appointment_repo.get_appointment_by_id(created.id)
        by_telegram = await appointment_repo.get_appointments_by_telegram_id(2002)

        assert by_id.proposal_message_id == 999
        assert by_telegram[0].proposal_message_id == 999

        await appointment_repo.update_proposal_message_id(created.id, None)

        by_id_cleared = await appointment_repo.get_appointment_by_id(created.id)
        by_telegram_cleared = await appointment_repo.get_appointments_by_telegram_id(2002)

        assert by_id_cleared.proposal_message_id is None
        assert by_telegram_cleared[0].proposal_message_id is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_update_admin_notification_message_id_round_trips_via_get_by_id_and_by_telegram_id():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        await user_repo.create_user(
            User(full_name="Иванов Иван", phone="+998901111111", role=Role.CLIENT, telegram_user_id=2004)
        )
        client = await user_repo.get_user_by_telegram_id(2004)

        created = await appointment_repo.create_appointment(_appointment_for(client.ID, "2026-07-01 10:00:00"))
        assert created.admin_notification_message_id is None

        await appointment_repo.update_admin_notification_message_id(created.id, 4242)

        by_id = await appointment_repo.get_appointment_by_id(created.id)
        by_telegram = await appointment_repo.get_appointments_by_telegram_id(2004)

        assert by_id.admin_notification_message_id == 4242
        assert by_telegram[0].admin_notification_message_id == 4242
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_update_proposed_by_round_trips_via_get_by_id_and_by_telegram_id():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        await user_repo.create_user(
            User(full_name="Иванов Иван", phone="+998901111111", role=Role.CLIENT, telegram_user_id=2003)
        )
        client = await user_repo.get_user_by_telegram_id(2003)

        created = await appointment_repo.create_appointment(_appointment_for(client.ID, "2026-07-01 10:00:00"))
        assert created.proposed_by is None

        await appointment_repo.update_proposed_by(created.id, CreatedBy.CLIENT)

        by_id = await appointment_repo.get_appointment_by_id(created.id)
        by_telegram = await appointment_repo.get_appointments_by_telegram_id(2003)

        assert by_id.proposed_by is CreatedBy.CLIENT
        assert by_telegram[0].proposed_by is CreatedBy.CLIENT

        await appointment_repo.update_proposed_by(created.id, CreatedBy.ADMIN)

        by_id_admin = await appointment_repo.get_appointment_by_id(created.id)
        by_telegram_admin = await appointment_repo.get_appointments_by_telegram_id(2003)

        assert by_id_admin.proposed_by is CreatedBy.ADMIN
        assert by_telegram_admin[0].proposed_by is CreatedBy.ADMIN

        await appointment_repo.update_proposed_by(created.id, None)

        by_id_cleared = await appointment_repo.get_appointment_by_id(created.id)
        by_telegram_cleared = await appointment_repo.get_appointments_by_telegram_id(2003)

        assert by_id_cleared.proposed_by is None
        assert by_telegram_cleared[0].proposed_by is None
    finally:
        await connection.close()


# --- Slot conflict detection: get_appointments_by_doctor_and_date ---

@pytest.mark.asyncio
async def test_get_appointments_by_doctor_and_date_returns_only_confirmed_for_that_day():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        doctor_id = 100

        confirmed = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 10:00", AppointmentStatus.CONFIRMED, "2026-07-01 10:00:00")
        )
        await connection.execute("UPDATE appointments SET admin_id = ? WHERE id = ?", (doctor_id, confirmed.id))

        pending = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 11:00", AppointmentStatus.PENDING, "2026-07-01 10:00:00")
        )
        await connection.execute("UPDATE appointments SET admin_id = ? WHERE id = ?", (doctor_id, pending.id))

        cancelled = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 12:00", AppointmentStatus.CANCELLED, "2026-07-01 10:00:00")
        )
        await connection.execute("UPDATE appointments SET admin_id = ? WHERE id = ?", (doctor_id, cancelled.id))

        expired = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-10 13:00", AppointmentStatus.EXPIRED, "2026-07-01 10:00:00")
        )
        await connection.execute("UPDATE appointments SET admin_id = ? WHERE id = ?", (doctor_id, expired.id))

        other_day_confirmed = await appointment_repo.create_appointment(
            _appointment_with_status(client.ID, "2026-07-11 10:00", AppointmentStatus.CONFIRMED, "2026-07-01 10:00:00")
        )
        await connection.execute("UPDATE appointments SET admin_id = ? WHERE id = ?", (doctor_id, other_day_confirmed.id))

        await connection.commit()

        result = await appointment_repo.get_appointments_by_doctor_and_date(doctor_id, "2026-07-10")

        assert [a.id for a in result] == [confirmed.id]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_update_appointment_price_round_trips_via_get_by_id_and_by_telegram_id():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        await user_repo.create_user(
            User(full_name="Иванов Иван", phone="+998901111111", role=Role.CLIENT, telegram_user_id=2005)
        )
        client = await user_repo.get_user_by_telegram_id(2005)

        created = await appointment_repo.create_appointment(_appointment_for(client.ID, "2026-07-01 10:00:00"))
        assert created.price is None

        await appointment_repo.update_appointment_price(created.id, 150000.0)

        by_id = await appointment_repo.get_appointment_by_id(created.id)
        by_telegram = await appointment_repo.get_appointments_by_telegram_id(2005)

        assert by_id.price == 150000.0
        assert by_telegram[0].price == 150000.0

        await appointment_repo.update_appointment_price(created.id, None)

        by_id_cleared = await appointment_repo.get_appointment_by_id(created.id)
        by_telegram_cleared = await appointment_repo.get_appointments_by_telegram_id(2005)

        assert by_id_cleared.price is None
        assert by_telegram_cleared[0].price is None
    finally:
        await connection.close()


# --- TOCTOU double-booking fix: idx_appointments_doctor_datetime_confirmed ---
# Regression tests for the partial unique index on (admin_id, datetime) WHERE
# status = 'confirmed', and the IntegrityError -> SlotUnavailableError translation
# in create_appointment / update_appointment / update_appointment_status.

def _slot_appointment(client_id: int, doctor_id: int, dt: str, status: AppointmentStatus) -> Appointment:
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        doctor_id=doctor_id,
        datetime=dt,
        purpose="Consultation",
        created_by=CreatedBy.ADMIN,
        status=status,
    )


@pytest.mark.asyncio
async def test_init_creates_partial_unique_index_on_clean_db():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        cursor = await connection.execute("PRAGMA index_list('appointments')")
        index_names = {row[1] for row in await cursor.fetchall()}

        assert "idx_appointments_doctor_datetime_confirmed" in index_names
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_create_appointment_raises_slot_unavailable_for_second_confirmed_same_slot():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        ivanov = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        petrov = await _seed_client(user_repo, "Петров Пётр", "+998902222222")
        doctor_id = 100
        slot = "2026-07-10 10:00"

        first = await appointment_repo.create_appointment(
            _slot_appointment(ivanov.ID, doctor_id, slot, AppointmentStatus.CONFIRMED)
        )

        with pytest.raises(SlotUnavailableError):
            await appointment_repo.create_appointment(
                _slot_appointment(petrov.ID, doctor_id, slot, AppointmentStatus.CONFIRMED)
            )

        untouched = await appointment_repo.get_appointment_by_id(first.id)
        assert untouched == first
        assert untouched.status is AppointmentStatus.CONFIRMED
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_create_appointment_allows_two_pending_appointments_for_same_slot():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        ivanov = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        petrov = await _seed_client(user_repo, "Петров Пётр", "+998902222222")
        doctor_id = 100
        slot = "2026-07-10 10:00"

        first = await appointment_repo.create_appointment(
            _slot_appointment(ivanov.ID, doctor_id, slot, AppointmentStatus.PENDING)
        )
        second = await appointment_repo.create_appointment(
            _slot_appointment(petrov.ID, doctor_id, slot, AppointmentStatus.PENDING)
        )

        assert first.id != second.id
        assert (await appointment_repo.get_appointment_by_id(first.id)).status is AppointmentStatus.PENDING
        assert (await appointment_repo.get_appointment_by_id(second.id)).status is AppointmentStatus.PENDING
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_update_appointment_status_raises_slot_unavailable_when_confirming_into_occupied_slot():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        ivanov = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        petrov = await _seed_client(user_repo, "Петров Пётр", "+998902222222")
        doctor_id = 100
        slot = "2026-07-10 10:00"

        first = await appointment_repo.create_appointment(
            _slot_appointment(ivanov.ID, doctor_id, slot, AppointmentStatus.PENDING)
        )
        second = await appointment_repo.create_appointment(
            _slot_appointment(petrov.ID, doctor_id, slot, AppointmentStatus.PENDING)
        )

        await appointment_repo.update_appointment_status(
            first.id, AppointmentStatus.CONFIRMED, "2026-07-01 09:00:00"
        )

        with pytest.raises(SlotUnavailableError):
            await appointment_repo.update_appointment_status(
                second.id, AppointmentStatus.CONFIRMED, "2026-07-01 09:05:00"
            )

        still_pending = await appointment_repo.get_appointment_by_id(second.id)
        assert still_pending.status is AppointmentStatus.PENDING
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_update_appointment_raises_slot_unavailable_when_confirming_into_occupied_slot():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        ivanov = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        petrov = await _seed_client(user_repo, "Петров Пётр", "+998902222222")
        doctor_id = 100
        slot = "2026-07-10 10:00"

        first = await appointment_repo.create_appointment(
            _slot_appointment(ivanov.ID, doctor_id, slot, AppointmentStatus.PENDING)
        )
        second = await appointment_repo.create_appointment(
            _slot_appointment(petrov.ID, doctor_id, slot, AppointmentStatus.PENDING)
        )

        await appointment_repo.update_appointment_status(
            first.id, AppointmentStatus.CONFIRMED, "2026-07-01 09:00:00"
        )

        second_confirmed = dataclasses.replace(second, status=AppointmentStatus.CONFIRMED)

        with pytest.raises(SlotUnavailableError):
            await appointment_repo.update_appointment(second.id, second_confirmed)

        still_pending = await appointment_repo.get_appointment_by_id(second.id)
        assert still_pending.status is AppointmentStatus.PENDING
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_update_appointment_allows_in_place_edit_of_already_confirmed_row():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        ivanov = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        doctor_id = 100
        slot = "2026-07-10 10:00"

        confirmed = await appointment_repo.create_appointment(
            _slot_appointment(ivanov.ID, doctor_id, slot, AppointmentStatus.CONFIRMED)
        )

        edited = dataclasses.replace(confirmed, purpose="Follow-up")
        await appointment_repo.update_appointment(confirmed.id, edited)

        updated = await appointment_repo.get_appointment_by_id(confirmed.id)
        assert updated.purpose == "Follow-up"
        assert updated.status is AppointmentStatus.CONFIRMED
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_create_appointment_fk_violation_raises_integrity_error_not_slot_unavailable(appointment_setup):
    appointment_repo, user = appointment_setup

    nonexistent_doctor_id = 999999
    appointment = _slot_appointment(
        user.ID, nonexistent_doctor_id, "2026-07-10 10:00", AppointmentStatus.PENDING
    )

    with pytest.raises(aiosqlite.IntegrityError) as excinfo:
        await appointment_repo.create_appointment(appointment)

    assert not isinstance(excinfo.value, SlotUnavailableError)


@pytest.mark.asyncio
async def test_init_skips_index_creation_and_does_not_crash_when_duplicate_confirmed_rows_exist(caplog):
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        doctor_id = 100
        slot = "2026-07-15 10:00"

        # The index already exists from the first init() call above (no duplicates
        # yet), so it must be dropped before we can force duplicate CONFIRMED rows
        # into the table via raw SQL, bypassing the repository entirely.
        await connection.execute("DROP INDEX IF EXISTS idx_appointments_doctor_datetime_confirmed")
        await connection.commit()

        for _ in range(2):
            await connection.execute(
                """
                INSERT INTO appointments (clinic_id, client_id, admin_id, datetime, purpose, created_by, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (1, client.ID, doctor_id, slot, "Consultation", CreatedBy.ADMIN.value, AppointmentStatus.CONFIRMED.value),
            )
        await connection.commit()

        with caplog.at_level("WARNING"):
            await appointment_repo.init()

        cursor = await connection.execute("PRAGMA index_list('appointments')")
        index_names = {row[1] for row in await cursor.fetchall()}
        assert "idx_appointments_doctor_datetime_confirmed" not in index_names
        assert "duplicate confirmed appointments" in caplog.text.lower()
    finally:
        await connection.close()
