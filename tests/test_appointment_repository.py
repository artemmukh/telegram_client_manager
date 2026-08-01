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
from bot.repositories.user_settings_repository import UserSettingsRepository
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

    await clinic_repo.init("zb")
    await user_repo.init()
    await UserSettingsRepository(connection).init()
    await staff_repo.init("zb")
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

    await clinic_repo.init("zb")
    await user_repo.init()
    await UserSettingsRepository(connection).init()
    await staff_repo.init("zb")
    await appointment_repo.init()

    return connection, user_repo, appointment_repo


async def _seed_client(user_repo: UserRepository, full_name: str, phone: str) -> User:
    await user_repo.create_user(
        User(full_name=full_name, phone=phone, role=Role.CLIENT)
    )
    return await user_repo.get_client_by_phone(phone)


async def _seed_doctor(user_repo: UserRepository, full_name: str, phone: str, telegram_user_id: int) -> User:
    """Seed a real admin/doctor user so admin_id can reference a row that
    actually exists in users(id) -- appointments.admin_id has a FOREIGN KEY
    on users(id), enforced now that AppointmentRepository.init() runs on a
    connection with PRAGMA foreign_keys = ON (production behavior).
    get_client_by_phone() filters role='client', so lookup goes through
    get_user_by_telegram_id() instead."""
    await user_repo.create_user(
        User(full_name=full_name, phone=phone, role=Role.ADMIN, telegram_user_id=telegram_user_id)
    )
    return await user_repo.get_user_by_telegram_id(telegram_user_id)


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
        await connection.execute(
            "INSERT INTO clinics (id, name, token) VALUES (2, 'Клиника 2', 'tok2')"
        )
        await connection.commit()

        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        doctor_a = await _seed_doctor(user_repo, "Доктор Первый", "+998900000100", telegram_user_id=100100)
        doctor_b = await _seed_doctor(user_repo, "Доктор Второй", "+998900000200", telegram_user_id=100200)

        own_doctor = await appointment_repo.create_appointment(
            Appointment(
                clinic_id=1, client_id=client.ID, doctor_id=doctor_a.ID,
                datetime="2026-07-10 10:00", purpose="Consultation",
                created_by=CreatedBy.ADMIN, status=AppointmentStatus.CONFIRMED,
            )
        )
        await appointment_repo.create_appointment(
            Appointment(
                clinic_id=1, client_id=client.ID, doctor_id=doctor_b.ID,
                datetime="2026-07-10 11:00", purpose="Consultation",
                created_by=CreatedBy.ADMIN, status=AppointmentStatus.CONFIRMED,
            )
        )
        await appointment_repo.create_appointment(
            Appointment(
                clinic_id=2, client_id=client.ID, doctor_id=doctor_a.ID,
                datetime="2026-07-10 12:00", purpose="Consultation",
                created_by=CreatedBy.ADMIN, status=AppointmentStatus.CONFIRMED,
            )
        )

        by_doctor = await appointment_repo.get_appointments_by_date_and_status_page(
            "2026-07-10", AppointmentStatus.CONFIRMED, 1, clinic_id=1, doctor_id=doctor_a.ID, per_page=10
        )
        assert [a.id for a in by_doctor] == [own_doctor.id]
        assert await appointment_repo.count_appointments_by_date_and_status(
            "2026-07-10", AppointmentStatus.CONFIRMED, clinic_id=1, doctor_id=doctor_a.ID
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
        doctor_a = await _seed_doctor(user_repo, "Доктор Первый", "+998900000100", telegram_user_id=100100)
        doctor_b = await _seed_doctor(user_repo, "Доктор Второй", "+998900000200", telegram_user_id=100200)

        own_doctor = await appointment_repo.create_appointment(
            Appointment(
                clinic_id=1, client_id=client.ID, doctor_id=doctor_a.ID,
                datetime="2026-07-01 10:00", purpose="Consultation",
                created_by=CreatedBy.ADMIN, status=AppointmentStatus.PENDING,
            )
        )
        other_doctor = await appointment_repo.create_appointment(
            Appointment(
                clinic_id=1, client_id=client.ID, doctor_id=doctor_b.ID,
                datetime="2026-07-02 10:00", purpose="Consultation",
                created_by=CreatedBy.ADMIN, status=AppointmentStatus.PENDING,
            )
        )
        other_clinic = await appointment_repo.create_appointment(
            Appointment(
                clinic_id=2, client_id=client.ID, doctor_id=doctor_a.ID,
                datetime="2026-07-03 10:00", purpose="Consultation",
                created_by=CreatedBy.ADMIN, status=AppointmentStatus.PENDING,
            )
        )

        own_only = await appointment_repo.get_appointments_page(1, clinic_id=1, doctor_id=doctor_a.ID, per_page=10)
        assert [a.id for a in own_only] == [own_doctor.id]
        assert await appointment_repo.count_appointments(clinic_id=1, doctor_id=doctor_a.ID) == 1

        clinic_wide = await appointment_repo.get_appointments_page(1, clinic_id=1, per_page=10)
        assert {a.id for a in clinic_wide} == {own_doctor.id, other_doctor.id}
        assert await appointment_repo.count_appointments(clinic_id=1) == 2

        assert other_clinic.id not in {a.id for a in clinic_wide}
        assert await appointment_repo.count_appointments(clinic_id=2) == 1

        by_status = await appointment_repo.get_appointments_by_status_page(
            AppointmentStatus.PENDING, 1, clinic_id=1, doctor_id=doctor_a.ID, per_page=10
        )
        assert [a.id for a in by_status] == [own_doctor.id]
        assert await appointment_repo.count_appointments_by_status(
            AppointmentStatus.PENDING, clinic_id=1, doctor_id=doctor_a.ID
        ) == 1

        by_name = await appointment_repo.get_appointments_by_name_and_status_page(
            "Иванов", AppointmentStatus.PENDING, 1, clinic_id=1, doctor_id=doctor_a.ID, per_page=10
        )
        assert [a.id for a in by_name] == [own_doctor.id]

        by_client = await appointment_repo.get_appointments_by_client_id(client.ID, clinic_id=1, doctor_id=doctor_a.ID)
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
async def test_get_appointments_by_doctor_and_date_default_statuses_match_slot_occupancy_rule():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        doctor = await _seed_doctor(user_repo, "Доктор Докторович", "+998900000100", telegram_user_id=100100)
        doctor_id = doctor.ID

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

        assert {a.id for a in result} == {confirmed.id, pending.id}
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
        doctor = await _seed_doctor(user_repo, "Доктор Докторович", "+998900000100", telegram_user_id=100100)
        doctor_id = doctor.ID
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
        doctor = await _seed_doctor(user_repo, "Доктор Докторович", "+998900000100", telegram_user_id=100100)
        doctor_id = doctor.ID
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
        doctor = await _seed_doctor(user_repo, "Доктор Докторович", "+998900000100", telegram_user_id=100100)
        doctor_id = doctor.ID
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
        doctor = await _seed_doctor(user_repo, "Доктор Докторович", "+998900000100", telegram_user_id=100100)
        doctor_id = doctor.ID
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
        doctor = await _seed_doctor(user_repo, "Доктор Докторович", "+998900000100", telegram_user_id=100100)
        doctor_id = doctor.ID
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
        doctor = await _seed_doctor(user_repo, "Доктор Докторович", "+998900000100", telegram_user_id=100100)
        doctor_id = doctor.ID
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


@pytest.mark.asyncio
async def test_init_with_max_bookings_per_slot_skips_index_creation():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        # The index already exists from the no-arg init() call inside
        # _in_memory_repos(); drop it so this test proves init(3) itself
        # does not (re)create it, matching what a fresh mm-instance DB
        # (which never calls init() with no argument) would look like.
        await connection.execute("DROP INDEX IF EXISTS idx_appointments_doctor_datetime_confirmed")
        await connection.commit()

        await appointment_repo.init(3)

        cursor = await connection.execute("PRAGMA index_list('appointments')")
        index_names = {row[1] for row in await cursor.fetchall()}

        assert "idx_appointments_doctor_datetime_confirmed" not in index_names
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_init_with_max_bookings_per_slot_drops_preexisting_index():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        # _in_memory_repos() already called init() with no argument, which
        # creates the single-booking-per-slot unique index (simulating a DB
        # that either ran under the old unconditional-index code, or a
        # zb-style boot on this same DB file before an mm upgrade).
        cursor = await connection.execute("PRAGMA index_list('appointments')")
        index_names = {row[1] for row in await cursor.fetchall()}
        assert "idx_appointments_doctor_datetime_confirmed" in index_names

        # Now simulate the mm upgrade path: init(3) on the SAME connection
        # must drop the stale index, or it keeps hard-blocking a 2nd
        # confirmed booking per slot even after the upgrade.
        await appointment_repo.init(3)

        cursor = await connection.execute("PRAGMA index_list('appointments')")
        index_names = {row[1] for row in await cursor.fetchall()}

        assert "idx_appointments_doctor_datetime_confirmed" not in index_names
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_create_appointment_allows_second_confirmed_same_slot_when_max_bookings_per_slot_set():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        ivanov = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        petrov = await _seed_client(user_repo, "Петров Пётр", "+998902222222")
        doctor = await _seed_doctor(user_repo, "Доктор Докторович", "+998900000100", telegram_user_id=100100)
        doctor_id = doctor.ID
        slot = "2026-07-10 10:00"

        await connection.execute("DROP INDEX IF EXISTS idx_appointments_doctor_datetime_confirmed")
        await connection.commit()
        await appointment_repo.init(3)

        first = await appointment_repo.create_appointment(
            _slot_appointment(ivanov.ID, doctor_id, slot, AppointmentStatus.CONFIRMED)
        )
        second = await appointment_repo.create_appointment(
            _slot_appointment(petrov.ID, doctor_id, slot, AppointmentStatus.CONFIRMED)
        )

        assert first.id != second.id
        assert (await appointment_repo.get_appointment_by_id(first.id)).status is AppointmentStatus.CONFIRMED
        assert (await appointment_repo.get_appointment_by_id(second.id)).status is AppointmentStatus.CONFIRMED
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_update_appointment_status_allows_second_confirmed_same_slot_when_max_bookings_per_slot_set():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        ivanov = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        petrov = await _seed_client(user_repo, "Петров Пётр", "+998902222222")
        doctor = await _seed_doctor(user_repo, "Доктор Докторович", "+998900000100", telegram_user_id=100100)
        doctor_id = doctor.ID
        slot = "2026-07-10 10:00"

        await connection.execute("DROP INDEX IF EXISTS idx_appointments_doctor_datetime_confirmed")
        await connection.commit()
        await appointment_repo.init(3)

        first = await appointment_repo.create_appointment(
            _slot_appointment(ivanov.ID, doctor_id, slot, AppointmentStatus.PENDING)
        )
        second = await appointment_repo.create_appointment(
            _slot_appointment(petrov.ID, doctor_id, slot, AppointmentStatus.PENDING)
        )

        await appointment_repo.update_appointment_status(
            first.id, AppointmentStatus.CONFIRMED, "2026-07-01 09:00:00"
        )
        await appointment_repo.update_appointment_status(
            second.id, AppointmentStatus.CONFIRMED, "2026-07-01 09:05:00"
        )

        first_confirmed = await appointment_repo.get_appointment_by_id(first.id)
        second_confirmed = await appointment_repo.get_appointment_by_id(second.id)
        assert first_confirmed.status is AppointmentStatus.CONFIRMED
        assert second_confirmed.status is AppointmentStatus.CONFIRMED
    finally:
        await connection.close()


# --- Atomic decision guards (try_*): compare-and-set race-closing behavior ---
#
# These prove the SQL guard actually closes the race window at the DB level:
# calling the same atomic method twice on the same row succeeds once and
# fails the second time, once the row no longer matches the guard condition
# (this is what makes two staff members racing on the same broadcast unable
# to both "win" the decision).


@pytest.mark.asyncio
async def test_try_confirm_or_reject_pending_second_call_fails_after_first_succeeds(appointment_setup):
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID, clinic_id=1))[0].id

    first = await appointment_repo.try_confirm_or_reject_pending(
        appointment_id, AppointmentStatus.CONFIRMED, user.ID, "2026-07-02 10:00:00"
    )
    second = await appointment_repo.try_confirm_or_reject_pending(
        appointment_id, AppointmentStatus.CANCELLED, user.ID, "2026-07-02 10:05:00"
    )

    assert first is True
    assert second is False
    updated = await appointment_repo.get_appointment_by_id(appointment_id)
    assert updated.status is AppointmentStatus.CONFIRMED
    assert updated.decided_by_user_id == user.ID


@pytest.mark.asyncio
async def test_try_propose_new_datetime_commits_new_datetime_and_demotes_confirmed_to_pending(appointment_setup):
    """try_propose_new_datetime no longer stages a proposal -- it commits the new
    datetime immediately and demotes the appointment to PENDING so it awaits an
    ordinary reconfirmation, clearing any stale proposed_datetime/proposed_by."""
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID, clinic_id=1))[0].id
    await appointment_repo.update_appointment_status(
        appointment_id, AppointmentStatus.CONFIRMED, "2026-07-01 09:00:00"
    )

    result = await appointment_repo.try_propose_new_datetime(
        appointment_id, "2026-07-05 10:00", user.ID, "2026-07-02 10:00:00", AppointmentStatus.CONFIRMED.value
    )

    assert result is True
    updated = await appointment_repo.get_appointment_by_id(appointment_id)
    assert updated.status is AppointmentStatus.PENDING
    assert updated.datetime == "2026-07-05 10:00"
    assert updated.status_updated_at == "2026-07-02 10:00:00"
    assert updated.proposed_datetime is None
    assert updated.proposed_by is None
    assert updated.decided_by_user_id == user.ID


@pytest.mark.asyncio
async def test_try_propose_new_datetime_second_admin_proposal_also_succeeds_last_writer_wins(appointment_setup):
    """Two admins racing to propose a new time on the same still-PENDING request
    now both succeed (pending -> pending is a no-op status transition for the
    CAS guard), with the second call's datetime winning -- real double-decision
    protection for a PENDING request comes from try_confirm_or_reject_pending's
    own guard, not from this method."""
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID, clinic_id=1))[0].id

    first = await appointment_repo.try_propose_new_datetime(
        appointment_id, "2026-07-05 10:00", user.ID, "2026-07-02 10:00:00", AppointmentStatus.PENDING.value
    )
    second = await appointment_repo.try_propose_new_datetime(
        appointment_id, "2026-07-06 11:00", user.ID, "2026-07-02 10:05:00", AppointmentStatus.PENDING.value
    )

    assert first is True
    assert second is True
    updated = await appointment_repo.get_appointment_by_id(appointment_id)
    assert updated.status is AppointmentStatus.PENDING
    assert updated.datetime == "2026-07-06 11:00"


@pytest.mark.asyncio
async def test_try_complete_appointment_second_call_fails_after_first_succeeds(appointment_setup):
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID, clinic_id=1))[0].id
    await appointment_repo.update_appointment_status(
        appointment_id, AppointmentStatus.CONFIRMED, "2026-07-01 09:00:00"
    )

    first = await appointment_repo.try_complete_appointment(appointment_id, user.ID, "2026-07-02 10:00:00")
    second = await appointment_repo.try_complete_appointment(appointment_id, user.ID, "2026-07-02 10:05:00")

    assert first is True
    assert second is False
    updated = await appointment_repo.get_appointment_by_id(appointment_id)
    assert updated.status is AppointmentStatus.COMPLETED
    assert updated.decided_by_user_id == user.ID


@pytest.mark.asyncio
async def test_try_resolve_client_reschedule_second_call_fails_after_first_accepted(appointment_setup):
    """Proves the compare-and-set guard on the client-reschedule accept path:
    once the first accept clears proposed_by/proposed_datetime, a second
    (racing) accept on the same appointment finds nothing left to resolve."""
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID, clinic_id=1))[0].id
    await appointment_repo.update_appointment_status(
        appointment_id, AppointmentStatus.CONFIRMED, "2026-07-01 09:00:00"
    )
    await appointment_repo.update_proposed_datetime(appointment_id, "2026-07-11 10:00")
    await appointment_repo.update_proposed_by(appointment_id, CreatedBy.CLIENT)

    first = await appointment_repo.try_resolve_client_reschedule(
        appointment_id, accept=True, decided_by_user_id=user.ID,
        status_updated_at="2026-07-02 10:00:00", new_datetime="2026-07-11 10:00",
    )
    second = await appointment_repo.try_resolve_client_reschedule(
        appointment_id, accept=True, decided_by_user_id=user.ID,
        status_updated_at="2026-07-02 10:05:00", new_datetime="2026-07-11 10:00",
    )

    assert first is True
    assert second is False
    updated = await appointment_repo.get_appointment_by_id(appointment_id)
    assert updated.status is AppointmentStatus.CONFIRMED
    assert updated.datetime == "2026-07-11 10:00"
    assert updated.proposed_datetime is None
    assert updated.proposed_by is None


@pytest.mark.asyncio
async def test_try_resolve_admin_proposal_accept_confirms_new_datetime_and_second_call_fails(appointment_setup):
    """CAS guard on the accept=True branch: the first client accept of an admin's
    proposed reschedule confirms the new datetime and clears the proposal; a
    racing second accept on the same (now-resolved) appointment finds nothing
    left to resolve."""
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID, clinic_id=1))[0].id
    await appointment_repo.update_appointment_status(
        appointment_id, AppointmentStatus.CONFIRMED, "2026-07-01 09:00:00"
    )
    await appointment_repo.update_proposed_datetime(appointment_id, "2026-07-15 10:00")
    await appointment_repo.update_proposed_by(appointment_id, CreatedBy.ADMIN)

    first = await appointment_repo.try_resolve_admin_proposal(
        appointment_id, accept=True, status_updated_at="2026-07-02 10:00:00", new_datetime="2026-07-15 10:00"
    )
    second = await appointment_repo.try_resolve_admin_proposal(
        appointment_id, accept=True, status_updated_at="2026-07-02 10:05:00", new_datetime="2026-07-16 10:00"
    )

    assert first is True
    assert second is False
    updated = await appointment_repo.get_appointment_by_id(appointment_id)
    assert updated.status is AppointmentStatus.CONFIRMED
    assert updated.datetime == "2026-07-15 10:00"
    assert updated.status_updated_at == "2026-07-02 10:00:00"
    assert updated.proposed_datetime is None
    assert updated.proposed_by is None


@pytest.mark.asyncio
async def test_try_resolve_admin_proposal_reject_cancels_and_writes_status_updated_at_and_second_call_fails(
    appointment_setup,
):
    """CAS guard on the accept=False branch: this branch originally didn't write
    status_updated_at at all (fixed mid-implementation), so assert it's now
    populated on the reject path, and that a racing second reject on the
    already-cancelled appointment can't re-write it."""
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID, clinic_id=1))[0].id
    await appointment_repo.update_appointment_status(
        appointment_id, AppointmentStatus.CONFIRMED, "2026-07-01 09:00:00"
    )
    await appointment_repo.update_proposed_datetime(appointment_id, "2026-07-15 10:00")
    await appointment_repo.update_proposed_by(appointment_id, CreatedBy.ADMIN)

    first = await appointment_repo.try_resolve_admin_proposal(
        appointment_id, accept=False, status_updated_at="2026-07-02 10:00:00"
    )
    second = await appointment_repo.try_resolve_admin_proposal(
        appointment_id, accept=False, status_updated_at="2026-07-02 10:05:00"
    )

    assert first is True
    assert second is False
    updated = await appointment_repo.get_appointment_by_id(appointment_id)
    assert updated.status is AppointmentStatus.CANCELLED
    assert updated.status_updated_at == "2026-07-02 10:00:00"
    assert updated.proposed_datetime is None
    assert updated.proposed_by is None


@pytest.mark.asyncio
async def test_try_propose_new_datetime_blocks_stale_pending_proposal_after_confirm_race(appointment_setup):
    """Regression test for the reviewed race: Admin A confirms a pending
    appointment, then Admin B races in with a stale try_propose_new_datetime
    call that still believes the appointment is 'pending'. Before the
    expected_status guard was added, this second call silently reopened the
    just-confirmed appointment; it must now fail and leave Admin A's confirm
    untouched."""
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID, clinic_id=1))[0].id

    admin_a = user.ID
    admin_b = user.ID + 1

    confirmed_by_admin_a = await appointment_repo.try_confirm_or_reject_pending(
        appointment_id, AppointmentStatus.CONFIRMED, admin_a, "2026-07-02 10:00:00"
    )
    stale_propose_by_admin_b = await appointment_repo.try_propose_new_datetime(
        appointment_id, "2026-07-10 10:00", admin_b, "2026-07-02 10:05:00", AppointmentStatus.PENDING.value
    )

    assert confirmed_by_admin_a is True
    assert stale_propose_by_admin_b is False

    updated = await appointment_repo.get_appointment_by_id(appointment_id)
    assert updated.status is AppointmentStatus.CONFIRMED
    assert updated.proposed_datetime is None
    assert updated.proposed_by is None
    assert updated.decided_by_user_id == admin_a


@pytest.mark.asyncio
async def test_try_propose_new_datetime_succeeds_with_expected_status_confirmed_for_admin_initiated_reschedule(
    appointment_setup,
):
    """Companion to the race-blocking test above: proves the legitimate
    admin-initiated reschedule on an already-confirmed appointment (no
    outstanding proposal) still works when expected_status matches the
    appointment's real current status, demoting it to PENDING with the new
    datetime committed directly (no staged proposal)."""
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID, clinic_id=1))[0].id
    await appointment_repo.try_confirm_or_reject_pending(
        appointment_id, AppointmentStatus.CONFIRMED, user.ID, "2026-07-02 10:00:00"
    )

    result = await appointment_repo.try_propose_new_datetime(
        appointment_id, "2026-07-10 10:00", user.ID, "2026-07-02 10:05:00", AppointmentStatus.CONFIRMED.value
    )

    assert result is True
    updated = await appointment_repo.get_appointment_by_id(appointment_id)
    assert updated.status is AppointmentStatus.PENDING
    assert updated.datetime == "2026-07-10 10:00"
    assert updated.proposed_datetime is None
    assert updated.proposed_by is None


# --- appointment_notifications (add_appointment_notification / get_appointment_notifications) ---


@pytest.mark.asyncio
async def test_add_and_get_appointment_notifications_filters_by_kind(appointment_setup):
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID, clinic_id=1))[0].id

    await appointment_repo.add_appointment_notification(appointment_id, chat_id=100, message_id=1, kind="booking")
    await appointment_repo.add_appointment_notification(appointment_id, chat_id=200, message_id=2, kind="booking")
    await appointment_repo.add_appointment_notification(appointment_id, chat_id=100, message_id=3, kind="reschedule")

    booking_notifications = await appointment_repo.get_appointment_notifications(appointment_id, "booking")
    reschedule_notifications = await appointment_repo.get_appointment_notifications(appointment_id, "reschedule")

    assert [n.chat_id for n in booking_notifications] == [100, 200]
    assert [n.message_id for n in booking_notifications] == [1, 2]
    assert len(reschedule_notifications) == 1
    assert reschedule_notifications[0].chat_id == 100
    assert reschedule_notifications[0].message_id == 3


# --- Phase 3 (REFACTOR_DB_PROMPT.md): price-after-purpose rebuild ---
#
# Target column order after the rebuild in AppointmentRepository (and what a
# fresh init() must converge to as well, even though the fresh CREATE TABLE
# above deliberately keeps the legacy order/admin_tg_id so both fresh and
# legacy databases flow through the same single rebuild path).
TARGET_APPOINTMENTS_COLUMN_ORDER = [
    "id", "clinic_id", "client_id", "admin_id", "datetime", "purpose", "price",
    "created_by", "status", "created_at", "status_updated_at",
    "notification_message_id", "proposed_datetime", "proposal_message_id",
    "proposed_by", "admin_notification_message_id", "decided_by_user_id",
]


async def _create_pre_phase3_appointments_table(connection: aiosqlite.Connection) -> None:
    """Simulate the appointments table as it existed before Phase 3 (price
    appended at the very end, admin_tg_id still present) -- matches a real
    pre-migration production database, so the rebuild guard (full column
    order mismatch) actually triggers."""
    await connection.execute("""
        CREATE TABLE appointments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id INTEGER NOT NULL,
            client_id INTEGER NOT NULL,
            admin_id INTEGER DEFAULT NULL,
            datetime TIMESTAMP NOT NULL,
            purpose TEXT,
            created_by TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status_updated_at TIMESTAMP DEFAULT NULL,
            admin_tg_id INTEGER DEFAULT NULL,
            notification_message_id INTEGER DEFAULT NULL,
            proposed_datetime TIMESTAMP DEFAULT NULL,
            proposal_message_id INTEGER DEFAULT NULL,
            proposed_by TEXT DEFAULT NULL,
            admin_notification_message_id INTEGER DEFAULT NULL,
            price REAL DEFAULT NULL,
            decided_by_user_id INTEGER DEFAULT NULL,

            FOREIGN KEY(clinic_id) REFERENCES clinics(id) ON DELETE CASCADE,
            FOREIGN KEY(client_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(admin_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)


async def _create_pre_admin_tg_id_appointments_table(connection: aiosqlite.Connection) -> None:
    """An even older schema than _create_pre_phase3_appointments_table: never
    carried admin_tg_id, notification_message_id, proposed_datetime,
    proposal_message_id, proposed_by, admin_notification_message_id, price,
    or decided_by_user_id at all. init()'s legacy ALTER ADD COLUMN guards
    backfill these by appending them at the end (in the order those guards
    run), never in the target position -- this is what proves the rebuild's
    staleness check must key on the full column order, not merely
    admin_tg_id's presence."""
    await connection.execute("""
        CREATE TABLE appointments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id INTEGER NOT NULL,
            client_id INTEGER NOT NULL,
            admin_id INTEGER DEFAULT NULL,
            datetime TIMESTAMP NOT NULL,
            purpose TEXT,
            created_by TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(clinic_id) REFERENCES clinics(id) ON DELETE CASCADE,
            FOREIGN KEY(client_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(admin_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)


class _ExecCallRecordingConnection:
    """Wraps an aiosqlite.Connection and records every SQL string passed to
    execute(), so tests can prove whether the appointments-table rebuild
    actually ran -- schema equality alone can't tell "rebuilt" apart from
    "already correct", since a rebuild produces an identical schema either
    way. Mirrors the equivalent helper in test_user_repository.py."""

    def __init__(self, connection: aiosqlite.Connection):
        self._connection = connection
        self.executed_sql: list[str] = []

    async def execute(self, sql, *args, **kwargs):
        self.executed_sql.append(sql)
        return await self._connection.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def rebuild_call_count(self) -> int:
        return sum(1 for sql in self.executed_sql if "appointments_new" in sql)


@pytest.mark.asyncio
async def test_appointments_rebuild_places_price_right_after_purpose_and_drops_admin_tg_id():
    """A fresh database's CREATE TABLE deliberately still carries admin_tg_id
    in legacy order (single rebuild path for fresh + legacy databases), so
    the very first init() must rebuild it into the target order."""
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        cursor = await connection.execute("PRAGMA table_info(appointments)")
        current_order = [row[1] for row in await cursor.fetchall()]

        assert current_order == TARGET_APPOINTMENTS_COLUMN_ORDER
        assert "admin_tg_id" not in current_order
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_appointments_rebuild_triggers_even_without_admin_tg_id_on_ancient_schema():
    """Regression lock for the staleness-check redesign: a genuinely ancient
    database that never carried admin_tg_id at all (so a presence-only check
    would wrongly conclude "already rebuilt") must still be detected as
    stale once init()'s legacy ALTER ADD COLUMN guards have appended the
    missing columns in the wrong order, and still get rebuilt into the
    target layout."""
    connection = await aiosqlite.connect(":memory:")
    try:
        clinic_repo = ClinicRepository(connection)
        user_repo = UserRepository(connection)
        await clinic_repo.init("zb")
        await user_repo.init()
        await UserSettingsRepository(connection).init()
        await StaffRepository(connection).init("zb")

        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")

        await _create_pre_admin_tg_id_appointments_table(connection)
        await connection.execute(
            "INSERT INTO appointments(clinic_id, client_id, datetime, purpose, created_by, status) "
            "VALUES (1, ?, '2026-08-01 10:00:00', 'Consultation', 'client', 'pending')",
            (client.ID,),
        )
        await connection.commit()

        cursor = await connection.execute("PRAGMA table_info(appointments)")
        pre_columns = [row[1] for row in await cursor.fetchall()]
        assert "admin_tg_id" not in pre_columns

        appointment_repo = AppointmentRepository(connection)
        await appointment_repo.init()

        cursor = await connection.execute("PRAGMA table_info(appointments)")
        current_order = [row[1] for row in await cursor.fetchall()]
        assert current_order == TARGET_APPOINTMENTS_COLUMN_ORDER

        appointment = await appointment_repo.get_appointment_by_id(1)
        assert appointment is not None
        assert appointment.purpose == "Consultation"
        assert appointment.status is AppointmentStatus.PENDING
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_appointments_rebuild_round_trips_all_existing_fields_and_preserves_fk():
    """Сквозной риск №1 regression lock: the rebuild's INSERT INTO
    appointments_new SELECT ... FROM appointments must carry every
    pre-existing field across without any positional shift, and
    PRAGMA foreign_key_check must stay clean afterwards. Uses asymmetric,
    non-default values for every field so a positional index slip in
    _row_to_appointment / APPOINTMENT_SELECT would fail this instead of
    passing by coincidence."""
    connection = await aiosqlite.connect(":memory:")
    try:
        clinic_repo = ClinicRepository(connection)
        user_repo = UserRepository(connection)
        staff_repo = StaffRepository(connection)
        await clinic_repo.init("zb")
        await user_repo.init()
        await UserSettingsRepository(connection).init()
        await staff_repo.init("zb")

        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        doctor = await _seed_doctor(user_repo, "Доктор Докторович", "+998900000100", telegram_user_id=100100)

        await _create_pre_phase3_appointments_table(connection)
        await connection.execute(
            """
            INSERT INTO appointments(
                clinic_id, client_id, admin_id, datetime, purpose, created_by,
                status, created_at, status_updated_at, admin_tg_id,
                notification_message_id, proposed_datetime, proposal_message_id,
                proposed_by, admin_notification_message_id, price, decided_by_user_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1, client.ID, doctor.ID, "2026-08-01 10:00:00", "Consultation",
                CreatedBy.CLIENT.value, AppointmentStatus.CONFIRMED.value,
                "2026-07-20 09:00:00", "2026-07-21 09:00:00", 999999,
                1111, "2026-08-05 11:00:00", 2222, CreatedBy.ADMIN.value,
                3333, 150000.5, client.ID,
            ),
        )
        await connection.commit()

        appointment_repo = AppointmentRepository(connection)
        await appointment_repo.init()

        fk_cursor = await connection.execute("PRAGMA foreign_key_check")
        assert await fk_cursor.fetchall() == []

        appointment = await appointment_repo.get_appointment_by_id(1)

        assert appointment is not None
        assert appointment.clinic_id == 1
        assert appointment.client_id == client.ID
        assert appointment.doctor_id == doctor.ID
        assert appointment.datetime == "2026-08-01 10:00:00"
        assert appointment.purpose == "Consultation"
        assert appointment.created_by is CreatedBy.CLIENT
        assert appointment.status is AppointmentStatus.CONFIRMED
        assert appointment.created_at == "2026-07-20 09:00:00"
        assert appointment.status_updated_at == "2026-07-21 09:00:00"
        assert appointment.notification_message_id == 1111
        assert appointment.proposed_datetime == "2026-08-05 11:00:00"
        assert appointment.proposal_message_id == 2222
        assert appointment.proposed_by is CreatedBy.ADMIN
        assert appointment.admin_notification_message_id == 3333
        assert appointment.price == 150000.5
        assert appointment.decided_by_user_id == client.ID

        cursor = await connection.execute("PRAGMA table_info(appointments)")
        current_order = [row[1] for row in await cursor.fetchall()]
        assert current_order == TARGET_APPOINTMENTS_COLUMN_ORDER
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_appointments_rebuild_is_idempotent_second_init_does_not_rebuild_again():
    """init() runs on every bot start. Without an idempotency guard, the
    rebuild would re-run (and re-scan/copy the whole table) on every
    restart. Schema equality before/after can't detect this (a rebuild's
    output schema is identical to a skipped rebuild's), so this instruments
    execute() calls directly to prove the second init() issues zero
    CREATE TABLE appointments_new / INSERT INTO appointments_new statements.
    Runs against a populated pre-Phase-3 (legacy) table, matching the
    equivalent users-table idempotency test's use of a populated table
    rather than an empty one."""
    connection = await aiosqlite.connect(":memory:")
    try:
        clinic_repo = ClinicRepository(connection)
        user_repo = UserRepository(connection)
        await clinic_repo.init("zb")
        await user_repo.init()
        await UserSettingsRepository(connection).init()
        await StaffRepository(connection).init("zb")

        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")

        await _create_pre_phase3_appointments_table(connection)
        await connection.execute(
            "INSERT INTO appointments(clinic_id, client_id, datetime, purpose, created_by, status) "
            "VALUES (1, ?, '2026-08-01 10:00:00', 'Consultation', 'client', 'pending')",
            (client.ID,),
        )
        await connection.commit()

        recorder = _ExecCallRecordingConnection(connection)
        appointment_repo = AppointmentRepository(recorder)

        await appointment_repo.init()
        assert recorder.rebuild_call_count() > 0, "first init() on a stale/legacy schema must rebuild"

        recorder.executed_sql.clear()
        await appointment_repo.init()
        assert recorder.rebuild_call_count() == 0, "second init() must be a no-op rebuild-wise"

        cursor = await connection.execute("PRAGMA table_info(appointments)")
        current_order = [row[1] for row in await cursor.fetchall()]
        assert current_order == TARGET_APPOINTMENTS_COLUMN_ORDER

        appointment = await appointment_repo.get_appointment_by_id(1)
        assert appointment is not None
        assert appointment.purpose == "Consultation"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_appointments_rebuild_preserves_appointment_notifications_fk():
    """appointment_notifications has a FOREIGN KEY on appointments(id) ON
    DELETE CASCADE. The rebuild (DROP + RENAME) must preserve appointment
    ids exactly, or pre-existing notification rows would be silently
    orphaned."""
    connection = await aiosqlite.connect(":memory:")
    try:
        clinic_repo = ClinicRepository(connection)
        user_repo = UserRepository(connection)
        await clinic_repo.init("zb")
        await user_repo.init()
        await UserSettingsRepository(connection).init()

        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")

        await _create_pre_phase3_appointments_table(connection)
        await connection.execute(
            """
            INSERT INTO appointments(clinic_id, client_id, datetime, purpose, created_by, status)
            VALUES (1, ?, '2026-08-01 10:00:00', 'Consultation', 'client', 'pending')
            """,
            (client.ID,),
        )
        # appointment_notifications is only created inside
        # AppointmentRepository.init(), so build it manually here to attach a
        # notification row to the pre-rebuild appointment before the rebuild runs.
        await connection.execute(
            """
            CREATE TABLE appointment_notifications(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
            )
            """
        )
        await connection.execute(
            "INSERT INTO appointment_notifications(appointment_id, chat_id, message_id, kind) "
            "VALUES (1, 555, 777, 'booking')"
        )
        await connection.commit()

        appointment_repo = AppointmentRepository(connection)
        await appointment_repo.init()

        fk_cursor = await connection.execute("PRAGMA foreign_key_check")
        assert await fk_cursor.fetchall() == []

        notifications = await appointment_repo.get_appointment_notifications(1, "booking")
        assert len(notifications) == 1
        assert notifications[0].appointment_id == 1
        assert notifications[0].chat_id == 555
        assert notifications[0].message_id == 777
    finally:
        await connection.close()


# --- get_appointments_by_telegram_id: standalone inline SELECT must stay in
# sync with APPOINTMENT_SELECT/_row_to_appointment (sквозной риск №1) ---

@pytest.mark.asyncio
async def test_get_appointments_by_telegram_id_returns_every_field_matching_get_by_id():
    """get_appointments_by_telegram_id runs its own inline SELECT (not
    APPOINTMENT_SELECT), so its column list/order must independently stay in
    sync with _row_to_appointment. Populates every readable field with
    distinct, non-default values and asserts each one individually on both
    read paths -- a coincidental None == None match (as in the minimal
    fixtures used elsewhere in this file) could mask an index shift."""
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        await user_repo.create_user(
            User(full_name="Иванов Иван", phone="+998901111111", role=Role.CLIENT, telegram_user_id=3001)
        )
        client = await user_repo.get_user_by_telegram_id(3001)
        doctor = await _seed_doctor(user_repo, "Доктор Докторович", "+998900000100", telegram_user_id=100100)
        await connection.execute(
            "INSERT INTO staff(telegram_user_id, clinic_id, is_doctor) VALUES (?, 1, 1)",
            (doctor.telegram_user_id,),
        )
        await connection.commit()

        created = await appointment_repo.create_appointment(
            Appointment(
                clinic_id=1, client_id=client.ID, doctor_id=doctor.ID,
                datetime="2026-08-01 10:00:00", purpose="Consultation",
                created_by=CreatedBy.CLIENT, status=AppointmentStatus.PENDING,
            )
        )
        await appointment_repo.try_confirm_or_reject_pending(
            created.id, AppointmentStatus.CONFIRMED, client.ID, "2026-08-01 09:00:00"
        )
        await appointment_repo.update_notification_message_id(created.id, 1111)
        await appointment_repo.update_proposed_datetime(created.id, "2026-08-05 11:00:00")
        await appointment_repo.update_proposal_message_id(created.id, 2222)
        await appointment_repo.update_proposed_by(created.id, CreatedBy.ADMIN)
        await appointment_repo.update_admin_notification_message_id(created.id, 3333)
        await appointment_repo.update_appointment_price(created.id, 150000.5)

        by_id = await appointment_repo.get_appointment_by_id(created.id)
        by_telegram_list = await appointment_repo.get_appointments_by_telegram_id(3001)
        assert len(by_telegram_list) == 1
        by_telegram = by_telegram_list[0]

        for appointment in (by_id, by_telegram):
            assert appointment.id == created.id
            assert appointment.clinic_id == 1
            assert appointment.client_id == client.ID
            assert appointment.doctor_id == doctor.ID
            assert appointment.datetime == "2026-08-01 10:00:00"
            assert appointment.purpose == "Consultation"
            assert appointment.created_by is CreatedBy.CLIENT
            assert appointment.status is AppointmentStatus.CONFIRMED
            assert appointment.status_updated_at == "2026-08-01 09:00:00"
            assert appointment.clinic_name == "Зуб Мудрости"
            assert appointment.client_full_name == "Иванов Иван"
            assert appointment.client_phone == "+998901111111"
            assert appointment.notification_message_id == 1111
            assert appointment.proposed_datetime == "2026-08-05 11:00:00"
            assert appointment.proposal_message_id == 2222
            assert appointment.proposed_by is CreatedBy.ADMIN
            assert appointment.admin_notification_message_id == 3333
            assert appointment.doctor_full_name == "Доктор Докторович"
            assert appointment.doctor_phone == "+998900000100"
            assert appointment.price == 150000.5
            assert appointment.doctor_is_doctor is True
            assert appointment.decided_by_user_id == client.ID

        assert by_id == by_telegram
    finally:
        await connection.close()
