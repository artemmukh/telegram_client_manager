import aiosqlite
import pytest

from bot.repositories.user_repository import UserRepository
from bot.repositories.user_settings_repository import UserSettingsRepository
from bot.utils.role import Role


async def _create_users_table(connection: aiosqlite.Connection) -> None:
    """UserSettingsRepository.init() expects `users` to already exist (it
    reads PRAGMA table_info(users) to decide whether to backfill), so tests
    that only exercise UserSettingsRepository create a minimal standalone
    users table by hand instead of going through UserRepository.init()."""
    await connection.execute("""
        CREATE TABLE users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER UNIQUE,
            full_name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL
        )
    """)
    await connection.commit()


@pytest.mark.asyncio
async def test_init_creates_table_on_users_only_db():
    connection = await aiosqlite.connect(":memory:")
    try:
        await _create_users_table(connection)

        user_settings_repo = UserSettingsRepository(connection)
        await user_settings_repo.init()

        cursor = await connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_settings'")
        assert await cursor.fetchone() is not None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_upsert_inserts_then_updates_existing_row():
    connection = await aiosqlite.connect(":memory:")
    try:
        await _create_users_table(connection)
        await connection.execute(
            "INSERT INTO users(telegram_user_id, full_name, phone) VALUES (1001, 'Иванов Иван', '+998901234567')"
        )
        await connection.commit()

        user_settings_repo = UserSettingsRepository(connection)
        await user_settings_repo.init()

        await user_settings_repo.upsert(1, True, False)
        first = await user_settings_repo.get_by_user_id(1)
        assert first.reminder_24h is True
        assert first.reminder_2h is False

        await user_settings_repo.upsert(1, False, False)
        second = await user_settings_repo.get_by_user_id(1)
        assert second.reminder_24h is False
        assert second.reminder_2h is False
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_get_by_user_id_returns_none_when_no_row_exists():
    connection = await aiosqlite.connect(":memory:")
    try:
        await _create_users_table(connection)

        user_settings_repo = UserSettingsRepository(connection)
        await user_settings_repo.init()

        assert await user_settings_repo.get_by_user_id(999) is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_init_backfills_exact_per_row_values_and_drops_columns_from_users():
    """Simulates a populated pre-Phase-2 `users` table (real reminder_24h/
    reminder_2h columns, asymmetric per-row values) going through the full
    boot sequence: user_repo.init() (adds gender/birth_date, keeps the
    reminder columns intact for this step) then user_settings_repo.init()
    (backfills the exact values into user_settings, then drops the columns
    from users)."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
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
        await connection.execute(
            """
            INSERT INTO users(telegram_user_id, full_name, phone, role, reminder_24h, reminder_2h)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (8001, "Иванов Иван", "+998901234510", Role.CLIENT.value, 0, 1),
        )
        await connection.execute(
            """
            INSERT INTO users(telegram_user_id, full_name, phone, role, reminder_24h, reminder_2h)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (8002, "Петров Петр", "+998901234511", Role.CLIENT.value, 1, 0),
        )
        await connection.execute(
            """
            INSERT INTO users(telegram_user_id, full_name, phone, role, reminder_24h, reminder_2h)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (8003, "Сидоров Сидор", "+998901234512", Role.CLIENT.value, 0, 0),
        )
        await connection.commit()

        user_repo = UserRepository(connection)
        await user_repo.init()

        user_settings_repo = UserSettingsRepository(connection)
        await user_settings_repo.init()

        settings_1 = await user_settings_repo.get_by_user_id(1)
        settings_2 = await user_settings_repo.get_by_user_id(2)
        settings_3 = await user_settings_repo.get_by_user_id(3)

        assert (settings_1.reminder_24h, settings_1.reminder_2h) == (False, True)
        assert (settings_2.reminder_24h, settings_2.reminder_2h) == (True, False)
        assert (settings_3.reminder_24h, settings_3.reminder_2h) == (False, False)

        users_columns = {row[1] for row in await (await connection.execute("PRAGMA table_info(users)")).fetchall()}
        assert "reminder_24h" not in users_columns
        assert "reminder_2h" not in users_columns

        # Reads through UserRepository must still reflect the exact per-row
        # values, now sourced from user_settings via USER_SELECT's COALESCE.
        user_1 = await user_repo.get_user_by_telegram_id(8001)
        user_2 = await user_repo.get_user_by_telegram_id(8002)
        user_3 = await user_repo.get_user_by_telegram_id(8003)
        assert (user_1.reminder_24h, user_1.reminder_2h) == (False, True)
        assert (user_2.reminder_24h, user_2.reminder_2h) == (True, False)
        assert (user_3.reminder_24h, user_3.reminder_2h) == (False, False)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_user_without_settings_row_defaults_to_true_via_get_user_by_id():
    """A user created after the user_settings split (no row in user_settings
    at all) must still read back with both reminder flags defaulting to
    true -- USER_SELECT's COALESCE(us.reminder_24h, 1)/COALESCE(us.reminder_2h, 1)
    is what supplies the default, not a row in user_settings."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        await user_repo.init()
        user_settings_repo = UserSettingsRepository(connection)
        await user_settings_repo.init()

        await connection.execute(
            "INSERT INTO users(telegram_user_id, full_name, phone, role) VALUES (?, ?, ?, ?)",
            (9001, "Новый Клиент", "+998901234513", Role.CLIENT.value),
        )
        await connection.commit()

        user = await user_repo.get_user_by_telegram_id(9001)

        assert await user_settings_repo.get_by_user_id(user.ID) is None
        assert user.reminder_24h is True
        assert user.reminder_2h is True
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_init_is_idempotent_second_call_is_a_no_op_and_preserves_data():
    connection = await aiosqlite.connect(":memory:")
    try:
        await _create_users_table(connection)
        await connection.execute(
            "INSERT INTO users(telegram_user_id, full_name, phone) VALUES (1001, 'Иванов Иван', '+998901234567')"
        )
        await connection.commit()

        user_settings_repo = UserSettingsRepository(connection)
        await user_settings_repo.init()
        await user_settings_repo.upsert(1, False, True)

        # Second init() must not error and must not reset/lose the row just written.
        await user_settings_repo.init()

        settings = await user_settings_repo.get_by_user_id(1)
        assert settings.reminder_24h is False
        assert settings.reminder_2h is True
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_init_on_users_table_without_legacy_reminder_columns_does_not_backfill_or_crash():
    """A `users` table that never had reminder_24h/reminder_2h (a fresh
    Phase-2 DB) must not trip the backfill branch -- init() should just
    create an empty user_settings table and return."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await _create_users_table(connection)
        await connection.execute(
            "INSERT INTO users(telegram_user_id, full_name, phone) VALUES (1001, 'Иванов Иван', '+998901234567')"
        )
        await connection.commit()

        user_settings_repo = UserSettingsRepository(connection)
        await user_settings_repo.init()

        assert await user_settings_repo.get_by_user_id(1) is None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_init_adds_language_column_with_default_ru_on_pre_existing_table():
    """A user_settings table that predates the language column (created by an
    older init() run, before this migration was added) must gain the column
    via ALTER TABLE, defaulting existing rows to 'ru'."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await _create_users_table(connection)
        await connection.execute(
            "INSERT INTO users(telegram_user_id, full_name, phone) VALUES (1001, 'Иванов Иван', '+998901234567')"
        )
        await connection.execute("""
            CREATE TABLE user_settings(
                user_id INTEGER PRIMARY KEY,
                reminder_24h INTEGER NOT NULL DEFAULT 1,
                reminder_2h  INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        await connection.execute(
            "INSERT INTO user_settings(user_id, reminder_24h, reminder_2h) VALUES (1, 1, 0)"
        )
        await connection.commit()

        user_settings_repo = UserSettingsRepository(connection)
        await user_settings_repo.init()

        columns = {row[1] for row in await (await connection.execute("PRAGMA table_info(user_settings)")).fetchall()}
        assert "language" in columns

        settings = await user_settings_repo.get_by_user_id(1)
        assert settings.language == "ru"
        assert settings.reminder_24h is True
        assert settings.reminder_2h is False
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_set_language_then_upsert_reminders_leaves_language_untouched():
    connection = await aiosqlite.connect(":memory:")
    try:
        await _create_users_table(connection)
        await connection.execute(
            "INSERT INTO users(telegram_user_id, full_name, phone) VALUES (1001, 'Иванов Иван', '+998901234567')"
        )
        await connection.commit()

        user_settings_repo = UserSettingsRepository(connection)
        await user_settings_repo.init()

        await user_settings_repo.set_language(1, "uz")
        await user_settings_repo.upsert(1, False, True)

        settings = await user_settings_repo.get_by_user_id(1)
        assert settings.language == "uz"
        assert settings.reminder_24h is False
        assert settings.reminder_2h is True
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_upsert_reminders_then_set_language_leaves_reminders_untouched():
    connection = await aiosqlite.connect(":memory:")
    try:
        await _create_users_table(connection)
        await connection.execute(
            "INSERT INTO users(telegram_user_id, full_name, phone) VALUES (1001, 'Иванов Иван', '+998901234567')"
        )
        await connection.commit()

        user_settings_repo = UserSettingsRepository(connection)
        await user_settings_repo.init()

        await user_settings_repo.upsert(1, False, True)
        await user_settings_repo.set_language(1, "uz")

        settings = await user_settings_repo.get_by_user_id(1)
        assert settings.language == "uz"
        assert settings.reminder_24h is False
        assert settings.reminder_2h is True
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_user_without_settings_row_defaults_to_ru_via_get_user_by_id():
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        user_repo = UserRepository(connection)
        await user_repo.init()
        user_settings_repo = UserSettingsRepository(connection)
        await user_settings_repo.init()

        await connection.execute(
            "INSERT INTO users(telegram_user_id, full_name, phone, role) VALUES (?, ?, ?, ?)",
            (9002, "Новый Клиент", "+998901234514", Role.CLIENT.value),
        )
        await connection.commit()

        user = await user_repo.get_user_by_telegram_id(9002)

        assert await user_settings_repo.get_by_user_id(user.ID) is None
        assert user.language == "ru"
    finally:
        await connection.close()
