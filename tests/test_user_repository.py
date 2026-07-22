import aiosqlite
import pytest
import pytest_asyncio

from bot.exceptions.user_exceptions import PhoneAlreadyExistsError, UserAlreadyExistsError, ValidationError
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.client_clinic_repository import ClientClinicRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.user_repository import UserRepository
from bot.repositories.user_settings_repository import UserSettingsRepository
from bot.services.utils.date_parser import get_current_tashkent_time
from bot.utils.role import Role

# Phase 1 of REFACTOR_DB_PROMPT.md target column order for the users-rebuild
# path (a pre-Phase-1 table that still physically carries reminder_24h/
# reminder_2h) -- gender and birth_date must sit right after full_name.
# Hardcoded here so any future drift in the rebuild's target order is caught
# by a failing assertion.
TARGET_USERS_COLUMN_ORDER = [
    "id", "telegram_user_id", "full_name", "gender", "birth_date",
    "phone", "clinic_id", "role", "created_at",
    "reminder_24h", "reminder_2h", "pending_full_name",
]

# Phase 2 (REFACTOR_DB_PROMPT.md): a brand-new database's CREATE TABLE no
# longer includes reminder_24h/reminder_2h at all -- those now live only in
# user_settings, created separately by UserSettingsRepository.
FRESH_DB_USERS_COLUMN_ORDER = [
    "id", "telegram_user_id", "full_name", "gender", "birth_date",
    "phone", "clinic_id", "role", "created_at", "pending_full_name",
]


class _ExecCallRecordingConnection:
    """Wraps an aiosqlite.Connection and records every SQL string passed to
    execute(), so tests can prove whether the users-table rebuild actually
    ran -- schema equality alone can't tell "rebuilt" apart from "already
    correct", since a rebuild produces an identical schema either way."""

    def __init__(self, connection: aiosqlite.Connection):
        self._connection = connection
        self.executed_sql: list[str] = []

    async def execute(self, sql, *args, **kwargs):
        self.executed_sql.append(sql)
        return await self._connection.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def rebuild_call_count(self) -> int:
        return sum(1 for sql in self.executed_sql if "users_new" in sql)


async def _create_pre_phase1_users_table(connection: aiosqlite.Connection) -> None:
    """Simulate a users table as it existed before Phase 1 (no gender/birth_date),
    already carrying pending_full_name and the reminder columns from earlier
    migrations, matching the schema real production databases would have."""
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
            reminder_2h INTEGER DEFAULT 1,
            pending_full_name TEXT DEFAULT NULL,

            FOREIGN KEY(clinic_id) REFERENCES clinics(id) ON DELETE CASCADE
        )
    """)


@pytest_asyncio.fixture
async def user_repo(tmp_path):
    connection = await aiosqlite.connect(tmp_path / "test.db")
    clinic_repo = ClinicRepository(connection)
    repo = UserRepository(connection)
    await clinic_repo.init()
    await repo.init()
    # Matches bot/run.py's boot sequence: user_settings_repo.init() must run
    # immediately after user_repo.init() so USER_SELECT's LEFT JOIN user_settings
    # has a table to join against.
    await UserSettingsRepository(connection).init()

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
async def test_update_user_telegram_id_collision_raises_domain_error_without_partial_write(user_repo):
    """TOCTOU regression: update_user_telegram_id used to let a UNIQUE-telegram_user_id
    collision surface as a raw aiosqlite.IntegrityError. It must now be translated into
    UserAlreadyExistsError, and the failed UPDATE must not partially apply -- client B's
    telegram_user_id stays exactly what it was before the call."""
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

    with pytest.raises(UserAlreadyExistsError):
        await user_repo.update_user_telegram_id(client_b.ID, 1001)

    unchanged = await user_repo.get_client_by_id(client_b.ID)
    assert unchanged.telegram_user_id == 1002


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
        await UserSettingsRepository(connection).init()
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
        await UserSettingsRepository(connection).init()
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
        await UserSettingsRepository(connection).init()
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
        await UserSettingsRepository(connection).init()
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
        await UserSettingsRepository(connection).init()
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
        await UserSettingsRepository(connection).init()
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
        await UserSettingsRepository(connection).init()
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
        await UserSettingsRepository(connection).init()

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
    """reminder_24h/reminder_2h no longer live on `users` -- they're read via
    USER_SELECT's COALESCE(us.reminder_24h, 1) against user_settings, and
    written through UserSettingsRepository.upsert() (UserRepository itself
    has no reminder-writing method anymore)."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        await user_repo.init()
        user_settings_repo = UserSettingsRepository(connection)
        await user_settings_repo.init()

        await user_repo.create_user(
            User(
                full_name="Иванов Иван",
                phone="+998901234567",
                role=Role.CLIENT,
                telegram_user_id=1001,
            )
        )

        user = await user_repo.get_user_by_telegram_id(1001)
        # No row in user_settings yet for this user -- COALESCE(..., 1) defaults
        # both flags to true.
        assert user.reminder_24h is True
        assert user.reminder_2h is True
        assert await user_settings_repo.get_by_user_id(user.ID) is None

        await user_settings_repo.upsert(user.ID, False, True)

        updated = await user_repo.get_user_by_telegram_id(1001)
        assert updated.reminder_24h is False
        assert updated.reminder_2h is True

        settings = await user_settings_repo.get_by_user_id(user.ID)
        assert settings.reminder_24h is False
        assert settings.reminder_2h is True
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
        await UserSettingsRepository(connection).init()

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
        await UserSettingsRepository(connection).init()

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
        await UserSettingsRepository(connection).init()

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
        await UserSettingsRepository(connection).init()

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
        await UserSettingsRepository(connection).init()

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
        await UserSettingsRepository(connection).init()

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
        await UserSettingsRepository(connection).init()

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
        await UserSettingsRepository(connection).init()

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
        await UserSettingsRepository(connection).init()

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


# --- Phase 1 (REFACTOR_DB_PROMPT.md): gender/birth_date rebuild ---

@pytest.mark.asyncio
async def test_users_rebuild_places_gender_and_birth_date_right_after_full_name():
    """Q1(b): gender/birth_date must be positioned right after full_name, not
    appended at the end -- this requires a full table rebuild rather than a
    plain ALTER ADD COLUMN. Assert the exact ordered column list, not just
    presence, so the target position is actually locked in."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        await _create_pre_phase1_users_table(connection)
        await connection.execute(
            "INSERT INTO users(telegram_user_id, full_name, phone, role) VALUES (?, ?, ?, ?)",
            (3001, "Мигрант Мигрантович", "+998901234501", Role.CLIENT.value),
        )
        await connection.commit()

        user_repo = UserRepository(connection)
        # Intentionally NOT followed by UserSettingsRepository(connection).init()
        # here: this test asserts the users-table column order immediately
        # after the Phase 1 rebuild, before UserSettingsRepository's own
        # backfill+drop step would remove reminder_24h/reminder_2h from users.
        await user_repo.init()

        cursor = await connection.execute("PRAGMA table_info(users)")
        current_order = [row[1] for row in await cursor.fetchall()]

        assert current_order == TARGET_USERS_COLUMN_ORDER
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_users_rebuild_round_trips_all_existing_user_fields():
    """Sквозной риск №1 regression lock: the rebuild's INSERT INTO users_new
    SELECT ... FROM users must carry every pre-existing field across without
    any positional shift. Uses asymmetric, non-default values for every field
    (distinct reminder flags, non-null pending_full_name, explicit created_at,
    a real clinic_id/role) so a positional index slip in _row_to_user would
    make this test fail instead of passing by coincidence."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        await connection.execute(
            "INSERT INTO clinics(id, name, token) VALUES (1, 'Клиника 1', 'tok-1')"
        )
        await _create_pre_phase1_users_table(connection)
        await connection.execute(
            """
            INSERT INTO users(
                telegram_user_id, full_name, phone, clinic_id, role,
                created_at, reminder_24h, reminder_2h, pending_full_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                4001,
                "Иванов Иван",
                "+998901234502",
                1,
                Role.ADMIN.value,
                "2026-07-20 10:15:00",
                0,
                1,
                "Петров Петр",
            ),
        )
        await connection.commit()

        user_repo = UserRepository(connection)
        await user_repo.init()
        await UserSettingsRepository(connection).init()

        user = await user_repo.get_user_by_id(1)

        assert user is not None
        assert user.telegram_user_id == 4001
        assert user.full_name == "Иванов Иван"
        assert user.gender is None
        assert user.birth_date is None
        assert user.phone == "+998901234502"
        assert user.clinic_id == 1
        assert user.role == Role.ADMIN
        assert user.created_at == "2026-07-20 10:15:00"
        assert user.reminder_24h is False
        assert user.reminder_2h is True
        assert user.pending_full_name == "Петров Петр"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_user_by_id_reads_gender_and_birth_date_written_directly():
    """Phase 1 ships schema + read support only (no writer method yet), so
    gender/birth_date are written via direct SQL here to prove _row_to_user
    reads indices 3/4 correctly."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        await user_repo.init()
        await UserSettingsRepository(connection).init()

        await user_repo.create_user(
            User(
                full_name="Иванов Иван",
                phone="+998901234503",
                role=Role.CLIENT,
                telegram_user_id=5001,
            )
        )
        created = await user_repo.get_user_by_telegram_id(5001)

        await connection.execute(
            "UPDATE users SET gender = ?, birth_date = ? WHERE id = ?",
            ("male", "1990-05-14", created.ID),
        )
        await connection.commit()

        user = await user_repo.get_user_by_id(created.ID)

        assert user.gender == "male"
        assert user.birth_date == "1990-05-14"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_users_rebuild_is_idempotent_second_init_does_not_rebuild_again():
    """init() runs on every bot start. Without an idempotency guard, the
    rebuild would re-run (and re-scan/copy the whole table) on every restart.
    Schema equality before/after can't detect this (a rebuild's output schema
    is identical to a skipped rebuild's), so this instruments execute() calls
    directly to prove the second init() issues zero CREATE TABLE users_new /
    INSERT INTO users_new statements."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        await _create_pre_phase1_users_table(connection)
        await connection.execute(
            "INSERT INTO users(telegram_user_id, full_name, phone, role) VALUES (?, ?, ?, ?)",
            (6001, "Иванов Иван", "+998901234504", Role.CLIENT.value),
        )
        await connection.commit()

        recorder = _ExecCallRecordingConnection(connection)
        user_repo = UserRepository(recorder)

        # Intentionally NOT paired with UserSettingsRepository(connection).init()
        # here: this test asserts users-table column order right after the
        # rebuild, before UserSettingsRepository would drop reminder_24h/
        # reminder_2h from users.
        await user_repo.init()
        assert recorder.rebuild_call_count() > 0, "first init() on a stale schema must rebuild"

        recorder.executed_sql.clear()
        await user_repo.init()
        assert recorder.rebuild_call_count() == 0, "second init() must be a no-op rebuild-wise"

        cursor = await connection.execute("PRAGMA table_info(users)")
        current_order = [row[1] for row in await cursor.fetchall()]
        assert current_order == TARGET_USERS_COLUMN_ORDER

        # Only now bring user_settings into existence (matching bot/run.py's
        # boot order), so USER_SELECT's LEFT JOIN has a table to join against.
        await UserSettingsRepository(connection).init()
        user = await user_repo.get_user_by_telegram_id(6001)
        assert user.full_name == "Иванов Иван"
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_fresh_db_creates_users_in_target_order_without_rebuild():
    """On a brand-new database, CREATE TABLE already produces the target
    column order, so the rebuild guard must skip entirely (no users_new
    CREATE/INSERT), not just leave the schema looking correct afterwards."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )

        recorder = _ExecCallRecordingConnection(connection)
        user_repo = UserRepository(recorder)
        await user_repo.init()
        await UserSettingsRepository(connection).init()

        assert recorder.rebuild_call_count() == 0, "fresh DB must not trigger a rebuild"

        cursor = await connection.execute("PRAGMA table_info(users)")
        current_order = [row[1] for row in await cursor.fetchall()]
        assert current_order == FRESH_DB_USERS_COLUMN_ORDER
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_users_rebuild_preserves_foreign_keys_from_appointments_and_client_clinics():
    """The users rebuild (DROP + rename) must not orphan rows in tables that
    hold a FOREIGN KEY on users(id) -- appointments (client_id/admin_id) and
    client_clinics (client_id). Populate both against a pre-Phase-1 users
    table, then run user_repo.init() (which triggers the rebuild) and assert
    PRAGMA foreign_key_check is empty and every relation still resolves."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        await connection.execute(
            "INSERT INTO clinics(id, name, token) VALUES (1, 'Клиника 1', 'tok-1')"
        )
        await _create_pre_phase1_users_table(connection)
        await connection.execute(
            "INSERT INTO users(telegram_user_id, full_name, phone, clinic_id, role) "
            "VALUES (?, ?, ?, ?, ?)",
            (7001, "Клиент Клиентович", "+998901234505", 1, Role.CLIENT.value),
        )
        await connection.execute(
            "INSERT INTO users(telegram_user_id, full_name, phone, clinic_id, role) "
            "VALUES (?, ?, ?, ?, ?)",
            (7002, "Доктор Докторович", "+998901234506", 1, Role.ADMIN.value),
        )
        await connection.commit()

        appointment_repo = AppointmentRepository(connection)
        await appointment_repo.init()
        client_clinic_repo = ClientClinicRepository(connection)
        await client_clinic_repo.init()

        await connection.execute(
            """
            INSERT INTO appointments(clinic_id, client_id, admin_id, datetime, created_by, status)
            VALUES (1, 1, 2, '2026-08-01 10:00:00', 'client', 'pending')
            """
        )
        await connection.commit()

        # Backfilled by client_clinic_repo.init() from role='client' + clinic_id.
        assert await client_clinic_repo.client_linked_to_clinic(1, 1) is True

        user_repo = UserRepository(connection)
        await user_repo.init()
        await UserSettingsRepository(connection).init()

        fk_cursor = await connection.execute("PRAGMA foreign_key_check")
        violations = await fk_cursor.fetchall()
        assert violations == []

        client = await user_repo.get_user_by_id(1)
        admin = await user_repo.get_user_by_id(2)
        assert client is not None and client.telegram_user_id == 7001
        assert admin is not None and admin.telegram_user_id == 7002
        assert await client_clinic_repo.client_linked_to_clinic(1, 1) is True

        appointment_cursor = await connection.execute(
            "SELECT client_id, admin_id FROM appointments WHERE clinic_id = 1"
        )
        appointment_row = await appointment_cursor.fetchone()
        assert appointment_row == (1, 2)
    finally:
        await connection.close()
