import aiosqlite
import pytest
import pytest_asyncio

from bot.exceptions.user_exceptions import UserAlreadyExistsError
from bot.models.user import User
from bot.repositories.user_repository import UserRepository
from bot.utils.role import Role


@pytest_asyncio.fixture
async def user_repo(tmp_path):
    repo = UserRepository(str(tmp_path / "test.db"))
    await repo.init()
    return repo


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
    assert by_phone.role == Role.CLIENT.value
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

    updated = User(
        full_name="\u041f\u0435\u0442\u0440\u043e\u0432 \u041f\u0435\u0442\u0440",
        phone="+998901234568",
        role=Role.ADMIN,
    )
    await user_repo.update_client(1001, updated)

    user = await user_repo.get_user_by_telegram_id(1001)

    assert user.full_name == updated.full_name
    assert user.phone == updated.phone
    assert user.role == Role.ADMIN.value


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

    await user_repo.delete_client(1001)

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
async def test_user_repository_enforces_unique_phone(user_repo):
    await user_repo.create_user(
        User(
            full_name="\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
            phone="+998901234567",
            role=Role.CLIENT,
            telegram_user_id=1001,
        )
    )

    with pytest.raises(UserAlreadyExistsError):
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
