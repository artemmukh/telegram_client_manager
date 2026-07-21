import aiosqlite
import pytest
import pytest_asyncio

from bot.exceptions.user_exceptions import PhoneAlreadyExistsError, UserAlreadyExistsError, ValidationError
from bot.models.user import User
from bot.repositories.client_clinic_repository import ClientClinicRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.user_repository import UserRepository
from bot.services.utils.date_parser import get_current_tashkent_time
from bot.utils.role import Role


@pytest_asyncio.fixture
async def user_repo(tmp_path):
    connection = await aiosqlite.connect(tmp_path / "test.db")
    clinic_repo = ClinicRepository(connection)
    repo = UserRepository(connection)
    await clinic_repo.init()
    await repo.init()

    yield repo

    await connection.close()


@pytest.mark.asyncio
async def test_user_repository_creates_and_reads_user_by_phone_and_telegram_id(user_repo):
    user = User(
        full_name="\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=1001,
    )

    await user_repo.create_user(user)

    by_phone = await user_repo.get_client_by_phone("+998901234567")
    by_telegram = await user_repo.get_user_by_telegram_id(1001)

    assert by_phone is not None
    assert by_phone.ID is not None
    assert by_phone.full_name == user.full_name
    assert by_phone.phone == user.phone
    assert by_phone.role == Role.CLIENT
    assert by_telegram == by_phone
    assert await user_repo.phone_exists("+998901234567") is True
    assert await user_repo.user_exists(1001) is True
    assert await user_repo.get_user_role(1001) == Role.CLIENT.value


@pytest.mark.asyncio
async def test_user_repository_updates_user(user_repo):
    await user_repo.create_user(
        User(
            full_name="\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
            phone="+998901234567",
            role=Role.CLIENT,
            telegram_user_id=1001,
        )
    )
    created = await user_repo.get_user_by_telegram_id(1001)

    updated = User(
        full_name="\u041f\u0435\u0442\u0440\u043e\u0432 \u041f\u0435\u0442\u0440",
        phone="+998901234568",
        role=Role.ADMIN,
    )
    await user_repo.update_client(created.ID, updated)

    user = await user_repo.get_user_by_telegram_id(1001)

    assert user.full_name == updated.full_name
    assert user.phone == updated.phone
    assert user.role == Role.ADMIN


@pytest.mark.asyncio
async def test_update_client_phone_collision_raises_domain_error_without_partial_write(user_repo):
    """TOCTOU regression: update_client used to let a UNIQUE-phone collision
    surface as a raw aiosqlite.IntegrityError. It must now be translated into
    PhoneAlreadyExistsError, and the failed UPDATE must not partially apply --
    client B's phone stays exactly what it was before the call."""
    await user_repo.create_user(
        User(
            full_name="Иванов Иван",
            phone="+998901234567",
            role=Role.CLIENT,
            telegram_user_id=1001,
        )
    )
    await user_repo.create_user(
        User(
            full_name="Петров Петр",
            phone="+998901234568",
            role=Role.CLIENT,
            telegram_user_id=1002,
        )
    )
    client_b = await user_repo.get_user_by_telegram_id(1002)

    colliding_update = User(
        full_name=client_b.full_name,
        phone="+998901234567",
        role=Role.CLIENT,
    )

    with pytest.raises(PhoneAlreadyExistsError):
        await user_repo.update_client(client_b.ID, colliding_update)

    unchanged = await user_repo.get_client_by_id(client_b.ID)
    assert unchanged.phone == "+998901234568"


@pytest.mark.asyncio
async def test_update_client_non_phone_integrity_error_raises_domain_error(user_repo):
    """A non-phone IntegrityError (NOT NULL on full_name) must not be
    mislabeled as PhoneAlreadyExistsError -- _is_phone_unique_violation only
    matches messages that mention both UNIQUE and phone. It must also not
    leak a raw aiosqlite.IntegrityError past the repository boundary."""
    await user_repo.create_user(
        User(
            full_name="Иванов Иван",
            phone="+998901234567",
            role=Role.CLIENT,
            telegram_user_id=1001,
        )
    )
    client = await user_repo.get_user_by_telegram_id(1001)

    update_with_null_name = User(
        full_name=None,
        phone=client.phone,
        role=Role.CLIENT,
    )

    with pytest.raises(ValidationError):
        await user_repo.update_client(client.ID, update_with_null_name)


@pytest.mark.asyncio
async def test_user_repository_deletes_user(user_repo):
    await user_repo.create_user(
        User(
            full_name="\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
            phone="+998901234567",
            role=Role.CLIENT,
            telegram_user_id=1001,
        )
    )
    created = await user_repo.get_user_by_telegram_id(1001)

    await user_repo.delete_client(created.ID)

    assert await user_repo.get_user_by_telegram_id(1001) is None
    assert await user_repo.user_exists(1001) is False
    assert await user_repo.phone_exists("+998901234567") is False


@pytest.mark.asyncio
async def test_user_repository_searches_users_by_name(user_repo):
    full_name = "\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d"
    await user_repo.create_user(
        User(full_name=full_name, phone="+998901234567", role=Role.CLIENT, telegram_user_id=1001)
    )
    await user_repo.create_user(
        User(full_name=full_name, phone="+998901234568", role=Role.CLIENT, telegram_user_id=1002)
    )

    users = await user_repo.get_clients_by_name(full_name)

    assert len(users) == 2
    assert [user.phone for user in users] == ["+998901234567", "+998901234568"]
    assert await user_repo.get_clients_by_name("\u041f\u0435\u0442\u0440\u043e\u0432 \u041f\u0435\u0442\u0440") == []


@pytest.mark.asyncio
async def test_get_clients_by_exact_name_matches_exact_name_within_clinic():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        client_clinic_repo = ClientClinicRepository(connection)
        await user_repo.init()
        await client_clinic_repo.init()

        full_name = "Иванов Иван"
        client_1 = User(full_name=full_name, phone="+998901234567", role=Role.CLIENT, clinic_id=1)
        await user_repo.create_user(client_1)
        await client_clinic_repo.link_client_to_clinic(client_1.ID, 1)

        client_2 = User(full_name=full_name, phone="+998901234568", role=Role.CLIENT, clinic_id=1)
        await user_repo.create_user(client_2)
        await client_clinic_repo.link_client_to_clinic(client_2.ID, 1)

        # Same name, different clinic - must not be returned.
        client_other_clinic = User(full_name=full_name, phone="+998901234569", role=Role.CLIENT, clinic_id=2)
        await user_repo.create_user(client_other_clinic)
        await client_clinic_repo.link_client_to_clinic(client_other_clinic.ID, 2)

        # Partial match (LIKE-style substring) must not be returned by exact match.
        client_partial = User(
            full_name="Иванов Иван Иванович", phone="+998901234570", role=Role.CLIENT, clinic_id=1
        )
        await user_repo.create_user(client_partial)
        await client_clinic_repo.link_client_to_clinic(client_partial.ID, 1)

        matches = await user_repo.get_clients_by_exact_name(full_name, 1)

        assert [user.phone for user in matches] == ["+998901234567", "+998901234568"]
        assert await user_repo.get_clients_by_exact_name(full_name, 2) == [
            (await user_repo.get_client_by_phone("+998901234569"))
        ]
        assert await user_repo.get_clients_by_exact_name("Петров Петр", 1) == []
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_clients_by_name_in_clinic_excludes_other_clinics():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        client_clinic_repo = ClientClinicRepository(connection)
        await user_repo.init()
        await client_clinic_repo.init()

        full_name = "Иванов Иван"
        client_in_clinic_1 = User(full_name=full_name, phone="+998901234567", role=Role.CLIENT, clinic_id=1)
        await user_repo.create_user(client_in_clinic_1)
        await client_clinic_repo.link_client_to_clinic(client_in_clinic_1.ID, 1)

        # Same name, different clinic - must not be returned.
        client_in_clinic_2 = User(full_name=full_name, phone="+998901234568", role=Role.CLIENT, clinic_id=2)
        await user_repo.create_user(client_in_clinic_2)
        await client_clinic_repo.link_client_to_clinic(client_in_clinic_2.ID, 2)

        matches = await user_repo.get_clients_by_name_in_clinic(full_name, 1)

        assert [user.phone for user in matches] == ["+998901234567"]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_clients_by_name_in_clinic_finds_client_linked_to_multiple_clinics():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        client_clinic_repo = ClientClinicRepository(connection)
        await user_repo.init()
        await client_clinic_repo.init()

        full_name = "Иванов Иван"
        client = User(full_name=full_name, phone="+998901234567", role=Role.CLIENT, clinic_id=1)
        await user_repo.create_user(client)
        await client_clinic_repo.link_client_to_clinic(client.ID, 1)
        await client_clinic_repo.link_client_to_clinic(client.ID, 2)

        matches_clinic_1 = await user_repo.get_clients_by_name_in_clinic(full_name, 1)
        matches_clinic_2 = await user_repo.get_clients_by_name_in_clinic(full_name, 2)

        assert [user.phone for user in matches_clinic_1] == ["+998901234567"]
        assert [user.phone for user in matches_clinic_2] == ["+998901234567"]
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_clients_by_name_page_in_clinic_and_count_exclude_other_clinics():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        client_clinic_repo = ClientClinicRepository(connection)
        await user_repo.init()
        await client_clinic_repo.init()

        full_name = "Иванов Иван"
        client_in_clinic_1 = User(full_name=full_name, phone="+998901234567", role=Role.CLIENT, clinic_id=1)
        await user_repo.create_user(client_in_clinic_1)
        await client_clinic_repo.link_client_to_clinic(client_in_clinic_1.ID, 1)

        client_in_clinic_2 = User(full_name=full_name, phone="+998901234568", role=Role.CLIENT, clinic_id=2)
        await user_repo.create_user(client_in_clinic_2)
        await client_clinic_repo.link_client_to_clinic(client_in_clinic_2.ID, 2)

        page = await user_repo.get_clients_by_name_page_in_clinic(full_name, 1, page=1, per_page=10)
        count = await user_repo.count_clients_by_name_in_clinic(full_name, 1)

        assert [user.phone for user in page] == ["+998901234567"]
        assert count == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_client_by_phone_in_clinic_excludes_other_clinics():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        client_clinic_repo = ClientClinicRepository(connection)
        await user_repo.init()
        await client_clinic_repo.init()

        client = User(full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, clinic_id=1)
        await user_repo.create_user(client)
        await client_clinic_repo.link_client_to_clinic(client.ID, 1)

        assert await user_repo.get_client_by_phone_in_clinic("+998901234567", 1) is not None
        assert await user_repo.get_client_by_phone_in_clinic("+998901234567", 2) is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_clients_page_in_clinic_and_count_exclude_other_clinics():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        client_clinic_repo = ClientClinicRepository(connection)
        await user_repo.init()
        await client_clinic_repo.init()

        client_in_clinic_1 = User(full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, clinic_id=1)
        await user_repo.create_user(client_in_clinic_1)
        await client_clinic_repo.link_client_to_clinic(client_in_clinic_1.ID, 1)

        client_in_clinic_2 = User(full_name="Петров Петр", phone="+998901234568", role=Role.CLIENT, clinic_id=2)
        await user_repo.create_user(client_in_clinic_2)
        await client_clinic_repo.link_client_to_clinic(client_in_clinic_2.ID, 2)

        page = await user_repo.get_clients_page_in_clinic(1, page=1, per_page=10)
        count = await user_repo.count_clients_in_clinic(1)

        assert [user.phone for user in page] == ["+998901234567"]
        assert count == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_clients_page_in_clinic_and_count_include_client_linked_to_multiple_clinics():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        client_clinic_repo = ClientClinicRepository(connection)
        await user_repo.init()
        await client_clinic_repo.init()

        client = User(full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, clinic_id=1)
        await user_repo.create_user(client)
        await client_clinic_repo.link_client_to_clinic(client.ID, 1)
        await client_clinic_repo.link_client_to_clinic(client.ID, 2)

        page_clinic_1 = await user_repo.get_clients_page_in_clinic(1, page=1, per_page=10)
        page_clinic_2 = await user_repo.get_clients_page_in_clinic(2, page=1, per_page=10)
        count_clinic_1 = await user_repo.count_clients_in_clinic(1)
        count_clinic_2 = await user_repo.count_clients_in_clinic(2)

        assert [user.phone for user in page_clinic_1] == ["+998901234567"]
        assert [user.phone for user in page_clinic_2] == ["+998901234567"]
        assert count_clinic_1 == 1
        assert count_clinic_2 == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_user_repository_enforces_unique_phone(user_repo):
    await user_repo.create_user(
        User(
            full_name="\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
            phone="+998901234567",
            role=Role.CLIENT,
            telegram_user_id=1001,
        )
    )

    with pytest.raises(PhoneAlreadyExistsError):
        await user_repo.create_user(
            User(
                full_name="\u041f\u0435\u0442\u0440\u043e\u0432 \u041f\u0435\u0442\u0440",
                phone="+998901234567",
                role=Role.CLIENT,
                telegram_user_id=1002,
            )
        )


@pytest.mark.asyncio
async def test_get_clients_by_name_page_empty_full_name_is_defensive_guard():
    connection = await aiosqlite.connect(":memory:")
    try:
        user_repo = UserRepository(connection)
        await user_repo.init()

        await user_repo.create_user(
            User(
                full_name="\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
                phone="+998901234567",
                role=Role.CLIENT,
                telegram_user_id=1001,
            )
        )

        assert await user_repo.get_clients_by_name_page("", 1, per_page=10) == []
        assert await user_repo.count_clients_by_name("") == 0

        # Whitespace-only input also strips down to an empty token list.
        assert await user_repo.get_clients_by_name_page("   ", 1, per_page=10) == []
        assert await user_repo.count_clients_by_name("   ") == 0

        assert await user_repo.get_clients_by_name("") == []
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_reminder_preferences_default_true_and_persist_updates():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        await user_repo.init()

        await user_repo.create_user(
            User(
                full_name="Иванов Иван",
                phone="+998901234567",
                role=Role.CLIENT,
                telegram_user_id=1001,
            )
        )

        user = await user_repo.get_user_by_telegram_id(1001)
        assert user.reminder_24h is True
        assert user.reminder_2h is True

        await user_repo.update_reminder_preferences(user.ID, False, True)

        updated = await user_repo.get_user_by_telegram_id(1001)
        assert updated.reminder_24h is False
        assert updated.reminder_2h is True
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_set_pending_full_name_stores_pending_value():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        await user_repo.init()

        await user_repo.create_user(
            User(
                full_name="Иванов Иван",
                phone="+998901234567",
                role=Role.CLIENT,
                telegram_user_id=1001,
            )
        )
        user = await user_repo.get_user_by_telegram_id(1001)

        await user_repo.set_pending_full_name(user.ID, "Петров Петр")

        updated = await user_repo.get_user_by_telegram_id(1001)
        assert updated.full_name == "Иванов Иван"
        assert updated.pending_full_name == "Петров Петр"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_resolve_pending_full_name_approve_applies_change():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        await user_repo.init()

        await user_repo.create_user(
            User(
                full_name="Иванов Иван",
                phone="+998901234567",
                role=Role.CLIENT,
                telegram_user_id=1001,
            )
        )
        user = await user_repo.get_user_by_telegram_id(1001)
        await user_repo.set_pending_full_name(user.ID, "Петров Петр")

        resolved = await user_repo.resolve_pending_full_name(user.ID, approve=True)

        assert resolved is not None
        assert resolved.full_name == "Петров Петр"
        assert resolved.pending_full_name is None

        # A second resolution attempt finds no pending request left.
        second_attempt = await user_repo.resolve_pending_full_name(user.ID, approve=True)
        assert second_attempt is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_resolve_pending_full_name_reject_clears_pending_value():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        await user_repo.init()

        await user_repo.create_user(
            User(
                full_name="Иванов Иван",
                phone="+998901234567",
                role=Role.CLIENT,
                telegram_user_id=1001,
            )
        )
        user = await user_repo.get_user_by_telegram_id(1001)
        await user_repo.set_pending_full_name(user.ID, "Петров Петр")

        resolved = await user_repo.resolve_pending_full_name(user.ID, approve=False)

        assert resolved is not None
        assert resolved.full_name == "Иванов Иван"
        assert resolved.pending_full_name is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_resolve_pending_full_name_returns_none_when_no_pending_request():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        await user_repo.init()

        await user_repo.create_user(
            User(
                full_name="Иванов Иван",
                phone="+998901234567",
                role=Role.CLIENT,
                telegram_user_id=1001,
            )
        )
        user = await user_repo.get_user_by_telegram_id(1001)

        resolved = await user_repo.resolve_pending_full_name(user.ID, approve=True)

        assert resolved is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_pending_full_name_migration_adds_column_for_existing_rows():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        # Simulate a pre-migration users table that predates pending_full_name.
        await connection.execute("""
            CREATE TABLE users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER UNIQUE,
                full_name TEXT NOT NULL,
                phone TEXT UNIQUE NOT NULL,
                clinic_id INTEGER DEFAULT NULL,
                role TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reminder_24h INTEGER DEFAULT 1,
                reminder_2h INTEGER DEFAULT 1
            )
        """)
        await connection.execute(
            "INSERT INTO users(telegram_user_id, full_name, phone, role) VALUES (?, ?, ?, ?)",
            (2002, "Петров Петр", "+998901234599", Role.CLIENT.value),
        )
        await connection.commit()

        user_repo = UserRepository(connection)
        await user_repo.init()

        user = await user_repo.get_user_by_telegram_id(2002)
        assert user.pending_full_name is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_reminder_columns_migration_backfills_existing_rows():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        # Simulate a pre-migration users table that predates the reminder columns.
        await connection.execute("""
            CREATE TABLE users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER UNIQUE,
                full_name TEXT NOT NULL,
                phone TEXT UNIQUE NOT NULL,
                clinic_id INTEGER DEFAULT NULL,
                role TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await connection.execute(
            "INSERT INTO users(telegram_user_id, full_name, phone, role) VALUES (?, ?, ?, ?)",
            (2002, "Петров Петр", "+998901234599", Role.CLIENT.value),
        )
        await connection.commit()

        user_repo = UserRepository(connection)
        await user_repo.init()

        user = await user_repo.get_user_by_telegram_id(2002)
        assert user.reminder_24h is True
        assert user.reminder_2h is True
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_create_user_persists_explicit_tashkent_created_at():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        await user_repo.init()

        tashkent_time = get_current_tashkent_time()
        await user_repo.create_user(
            User(
                full_name="Иванов Иван",
                phone="+998901234567",
                role=Role.CLIENT,
                telegram_user_id=1001,
                created_at=tashkent_time,
            )
        )

        by_telegram = await user_repo.get_user_by_telegram_id(1001)
        by_phone = await user_repo.get_client_by_phone("+998901234567")

        # The stored value must match the explicit Python-side timestamp
        # exactly, proving create_user() writes it (rather than falling
        # back to SQLite's CURRENT_TIMESTAMP default, which is UTC).
        assert by_telegram.created_at == tashkent_time
        assert by_phone.created_at == tashkent_time
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_create_user_without_created_at_stores_null_not_sql_default():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        await user_repo.init()

        await user_repo.create_user(
            User(
                full_name="Иванов Иван",
                phone="+998901234567",
                role=Role.CLIENT,
                telegram_user_id=1001,
            )
        )

        user = await user_repo.get_user_by_telegram_id(1001)

        # created_at defaults to None on the model, and since the column
        # is now explicitly listed in the INSERT, SQLite does NOT fall
        # back to its CURRENT_TIMESTAMP default -- NULL is written as-is.
        assert user.created_at is None
    finally:
        await connection.close()


# --- visibility_scope (admin_visibility_scope feature) ---

@pytest.mark.asyncio
async def test_get_staff_users_by_clinic_id_still_includes_clinic_scope_admins():
    """DoD: list_bookable_staff (self-booking) filters out 'clinic'-scope admins
    (via StaffRepository), but get_staff_users_by_clinic_id itself (used by
    client_notifications for broadcast) must remain untouched and keep
    returning all admins of the clinic regardless of visibility_scope, which
    now lives on Staff, not User."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        await user_repo.init()

        await user_repo.create_user(
            User(full_name="Елена Врач", phone="+998901111111", role=Role.ADMIN, telegram_user_id=226655040, clinic_id=1)
        )
        await user_repo.create_user(
            User(full_name="Артём Управляющий", phone="+998902222222", role=Role.ADMIN, telegram_user_id=685889801, clinic_id=1)
        )

        staff = await user_repo.get_staff_users_by_clinic_id(1)

        assert {member.telegram_user_id for member in staff} == {226655040, 685889801}
    finally:
        await connection.close()
