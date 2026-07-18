import aiosqlite
import pytest

from bot.repositories.client_clinic_repository import ClientClinicRepository


async def _connection_with_users_and_clinics():
    connection = await aiosqlite.connect(":memory:")
    await connection.execute("PRAGMA foreign_keys = ON")
    await connection.execute("""
        CREATE TABLE clinics(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT DEFAULT NULL,
            token TEXT UNIQUE NOT NULL
        )
    """)
    await connection.execute("""
        CREATE TABLE users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER UNIQUE,
            full_name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            clinic_id INTEGER DEFAULT NULL,
            role TEXT DEFAULT NULL,
            FOREIGN KEY(clinic_id) REFERENCES clinics(id) ON DELETE CASCADE
        )
    """)
    await connection.commit()
    return connection


@pytest.mark.asyncio
async def test_link_client_to_clinic_creates_row():
    connection = await _connection_with_users_and_clinics()
    try:
        await connection.execute("INSERT INTO clinics(id, token) VALUES (1, 'a')")
        await connection.execute(
            "INSERT INTO users(id, full_name, phone, role) VALUES (1, 'John', '111', 'client')"
        )
        await connection.commit()

        repo = ClientClinicRepository(connection)
        await repo.init()

        await repo.link_client_to_clinic(1, 1)

        assert await repo.client_linked_to_clinic(1, 1) is True
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_link_client_to_clinic_is_idempotent():
    connection = await _connection_with_users_and_clinics()
    try:
        await connection.execute("INSERT INTO clinics(id, token) VALUES (1, 'a')")
        await connection.execute(
            "INSERT INTO users(id, full_name, phone, role) VALUES (1, 'John', '111', 'client')"
        )
        await connection.commit()

        repo = ClientClinicRepository(connection)
        await repo.init()

        await repo.link_client_to_clinic(1, 1)
        await repo.link_client_to_clinic(1, 1)

        cursor = await connection.execute(
            "SELECT COUNT(*) FROM client_clinics WHERE client_id = 1 AND clinic_id = 1"
        )
        row = await cursor.fetchone()
        assert row[0] == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_client_linked_to_clinic_false_before_linking_and_for_unlinked_pair():
    connection = await _connection_with_users_and_clinics()
    try:
        await connection.execute("INSERT INTO clinics(id, token) VALUES (1, 'a'), (2, 'b')")
        await connection.execute(
            "INSERT INTO users(id, full_name, phone, role) VALUES (1, 'John', '111', 'client')"
        )
        await connection.commit()

        repo = ClientClinicRepository(connection)
        await repo.init()

        assert await repo.client_linked_to_clinic(1, 1) is False

        await repo.link_client_to_clinic(1, 1)

        assert await repo.client_linked_to_clinic(1, 1) is True
        assert await repo.client_linked_to_clinic(1, 2) is False
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_client_clinic_ids_returns_all_linked_ids_or_empty():
    connection = await _connection_with_users_and_clinics()
    try:
        await connection.execute("INSERT INTO clinics(id, token) VALUES (1, 'a'), (2, 'b')")
        await connection.execute(
            "INSERT INTO users(id, full_name, phone, role) VALUES (1, 'John', '111', 'client')"
        )
        await connection.commit()

        repo = ClientClinicRepository(connection)
        await repo.init()

        assert await repo.get_client_clinic_ids(1) == []

        await repo.link_client_to_clinic(1, 1)
        await repo.link_client_to_clinic(1, 2)

        ids = await repo.get_client_clinic_ids(1)
        assert sorted(ids) == [1, 2]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_init_backfills_home_clinic_link_for_preexisting_clients():
    # Simulate a pre-existing database: a client row with a clinic_id already
    # exists before ClientClinicRepository.init() ever runs. init() must
    # backfill a link row for their home clinic.
    connection = await _connection_with_users_and_clinics()
    try:
        await connection.execute("INSERT INTO clinics(id, token) VALUES (1, 'a')")
        await connection.execute(
            "INSERT INTO users(id, full_name, phone, clinic_id, role) "
            "VALUES (1, 'John', '111', 1, 'client')"
        )
        await connection.commit()

        repo = ClientClinicRepository(connection)
        await repo.init()

        assert await repo.client_linked_to_clinic(1, 1) is True
        assert await repo.get_client_clinic_ids(1) == [1]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_init_is_idempotent_on_second_call():
    connection = await _connection_with_users_and_clinics()
    try:
        await connection.execute("INSERT INTO clinics(id, token) VALUES (1, 'a')")
        await connection.execute(
            "INSERT INTO users(id, full_name, phone, clinic_id, role) "
            "VALUES (1, 'John', '111', 1, 'client')"
        )
        await connection.commit()

        repo = ClientClinicRepository(connection)
        await repo.init()
        await repo.init()

        cursor = await connection.execute("SELECT COUNT(*) FROM client_clinics")
        row = await cursor.fetchone()
        assert row[0] == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_init_does_not_backfill_staff_or_admin_rows():
    connection = await _connection_with_users_and_clinics()
    try:
        await connection.execute("INSERT INTO clinics(id, token) VALUES (1, 'a')")
        await connection.execute(
            "INSERT INTO users(id, full_name, phone, clinic_id, role) "
            "VALUES (1, 'Admin', '222', 1, 'admin')"
        )
        await connection.commit()

        repo = ClientClinicRepository(connection)
        await repo.init()

        assert await repo.get_client_clinic_ids(1) == []
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_deleting_user_cascades_to_client_clinics():
    connection = await _connection_with_users_and_clinics()
    try:
        await connection.execute("INSERT INTO clinics(id, token) VALUES (1, 'a')")
        await connection.execute(
            "INSERT INTO users(id, full_name, phone, role) VALUES (1, 'John', '111', 'client')"
        )
        await connection.commit()

        repo = ClientClinicRepository(connection)
        await repo.init()
        await repo.link_client_to_clinic(1, 1)

        await connection.execute("DELETE FROM users WHERE id = 1")
        await connection.commit()

        cursor = await connection.execute("SELECT COUNT(*) FROM client_clinics")
        row = await cursor.fetchone()
        assert row[0] == 0
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_deleting_clinic_cascades_only_that_clinics_links():
    # Deleting a clinic must remove links to that clinic but must not touch
    # the client users row (users.clinic_id FK cascade is out of scope here)
    # nor their links to other clinics.
    connection = await _connection_with_users_and_clinics()
    try:
        await connection.execute("INSERT INTO clinics(id, token) VALUES (1, 'a'), (2, 'b')")
        await connection.execute(
            "INSERT INTO users(id, full_name, phone, role) VALUES (1, 'John', '111', 'client')"
        )
        await connection.commit()

        repo = ClientClinicRepository(connection)
        await repo.init()
        await repo.link_client_to_clinic(1, 1)
        await repo.link_client_to_clinic(1, 2)

        await connection.execute("DELETE FROM clinics WHERE id = 1")
        await connection.commit()

        remaining_ids = await repo.get_client_clinic_ids(1)
        assert remaining_ids == [2]

        cursor = await connection.execute("SELECT COUNT(*) FROM users WHERE id = 1")
        row = await cursor.fetchone()
        assert row[0] == 1
    finally:
        await connection.close()
