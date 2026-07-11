import aiosqlite
import pytest
import pytest_asyncio

from bot.models.appointment import Appointment
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.user_repository import UserRepository
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


@pytest_asyncio.fixture
async def appointment_setup(tmp_path):
    connection = await aiosqlite.connect(tmp_path / "test.db")
    await connection.execute("PRAGMA foreign_keys = ON")

    clinic_repo = ClinicRepository(connection)
    user_repo = UserRepository(connection)
    appointment_repo = AppointmentRepository(connection)

    await clinic_repo.init()
    await user_repo.init()
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

    by_client = await appointment_repo.get_appointments_by_client_id(user.ID)
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
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID))[0].id

    await appointment_repo.update_appointment_status(appointment_id, AppointmentStatus.CONFIRMED)

    updated = await appointment_repo.get_appointment_by_id(appointment_id)
    assert updated.status is AppointmentStatus.CONFIRMED


@pytest.mark.asyncio
async def test_deletes_appointment(appointment_setup):
    appointment_repo, user = appointment_setup
    await appointment_repo.create_appointment(_appointment(user.ID))
    appointment_id = (await appointment_repo.get_appointments_by_client_id(user.ID))[0].id

    await appointment_repo.delete_appointment(appointment_id)

    assert await appointment_repo.get_appointment_by_id(appointment_id) is None
    assert await appointment_repo.appointment_exists(appointment_id) is False


# --- Pagination methods (in-memory sqlite, to avoid Windows file-lock flakiness) ---

async def _in_memory_repos():
    connection = await aiosqlite.connect(":memory:")
    clinic_repo = ClinicRepository(connection)
    user_repo = UserRepository(connection)
    appointment_repo = AppointmentRepository(connection)

    await clinic_repo.init()
    await user_repo.init()
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

        assert await appointment_repo.count_appointments() == 5

        page_one = await appointment_repo.get_appointments_page(1, per_page=2)
        page_two = await appointment_repo.get_appointments_page(2, per_page=2)
        page_three = await appointment_repo.get_appointments_page(3, per_page=2)

        # Newest created_at first (DESC), page 1 = offset 0.
        assert [a.created_at for a in page_one] == ["2026-07-05 10:00:00", "2026-07-04 10:00:00"]
        assert [a.created_at for a in page_two] == ["2026-07-03 10:00:00", "2026-07-02 10:00:00"]
        assert [a.created_at for a in page_three] == ["2026-07-01 10:00:00"]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_name_page_matches_multi_token_full_name():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        ivanov = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        petrov = await _seed_client(user_repo, "Петров Пётр", "+998902222222")
        sidorov = await _seed_client(user_repo, "Сидоров Семён", "+998903333333")

        await appointment_repo.create_appointment(_appointment_for(ivanov.ID, "2026-07-01 10:00:00"))
        await appointment_repo.create_appointment(_appointment_for(petrov.ID, "2026-07-02 10:00:00"))
        await appointment_repo.create_appointment(_appointment_for(sidorov.ID, "2026-07-03 10:00:00"))

        # Multi-token search matches either token (OR), so both "Иванов" and "Пётр" match.
        count = await appointment_repo.count_appointments_by_name("Иванов Пётр")
        page = await appointment_repo.get_appointments_by_name_page("Иванов Пётр", 1, per_page=10)

        assert count == 2
        assert count == len(page)
        assert {a.client_id for a in page} == {ivanov.ID, petrov.ID}
        assert sidorov.ID not in {a.client_id for a in page}
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_name_page_normalizes_case_before_matching():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        ivanov = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        await appointment_repo.create_appointment(_appointment_for(ivanov.ID, "2026-07-01 10:00:00"))

        # Input is lower-cased; repository .title()-normalizes it before LIKE.
        count = await appointment_repo.count_appointments_by_name("иванов")
        page = await appointment_repo.get_appointments_by_name_page("иванов", 1, per_page=10)

        assert count == 1
        assert len(page) == 1
        assert page[0].client_id == ivanov.ID
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_appointments_by_name_page_empty_full_name_is_defensive_guard():
    connection, user_repo, appointment_repo = await _in_memory_repos()
    try:
        client = await _seed_client(user_repo, "Иванов Иван", "+998901111111")
        await appointment_repo.create_appointment(_appointment_for(client.ID, "2026-07-01 10:00:00"))

        assert await appointment_repo.get_appointments_by_name_page("", 1, per_page=10) == []
        assert await appointment_repo.count_appointments_by_name("") == 0

        # Whitespace-only input also strips down to an empty token list.
        assert await appointment_repo.get_appointments_by_name_page("   ", 1, per_page=10) == []
        assert await appointment_repo.count_appointments_by_name("   ") == 0
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

        total_count = await appointment_repo.count_appointments_by_client_id(target.ID)
        page_one = await appointment_repo.get_appointments_by_client_id_page(target.ID, 1, per_page=2)
        page_two = await appointment_repo.get_appointments_by_client_id_page(target.ID, 2, per_page=2)

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
        assert await appointment_repo.count_appointments_by_client_id(client.ID) == 0
        assert await appointment_repo.get_appointments_by_client_id_page(client.ID, 1, per_page=10) == []

        await appointment_repo.create_appointment(_appointment_for(client.ID, "2026-07-01 10:00:00"))

        count = await appointment_repo.count_appointments_by_client_id(client.ID)
        page = await appointment_repo.get_appointments_by_client_id_page(client.ID, 1, per_page=10)

        assert count == len(page) == 1
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
