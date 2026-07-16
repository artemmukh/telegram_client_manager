import aiosqlite
import pytest

from bot.repositories.staff_repository import StaffRepository


# --- visibility_scope backfill (moved from users to staff) ---

@pytest.mark.asyncio
async def test_visibility_scope_backfill_transfers_value_from_users():
    """A telegram_id present in both users (still carrying the legacy physical
    visibility_scope column and a value from before the field moved off User)
    and staff: the migration must carry that value over onto Staff."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        # Simulate a users table that still physically has the legacy
        # visibility_scope column -- UserRepository no longer manages it, but
        # a database that predates this refactor still has it on disk.
        await connection.execute("""
            CREATE TABLE users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER UNIQUE,
                visibility_scope TEXT DEFAULT NULL
            )
        """)
        await connection.execute(
            "INSERT INTO users(telegram_user_id, visibility_scope) VALUES (?, ?)",
            (685889801, "clinic"),
        )
        await connection.commit()

        staff_repo = StaffRepository(connection)
        await staff_repo.init()

        staff = await staff_repo.get_staff(685889801)
        assert staff.visibility_scope == "clinic"

        cursor = await connection.execute("PRAGMA table_info(users)")
        users_columns = {row[1] for row in await cursor.fetchall()}
        assert "visibility_scope" not in users_columns, (
            "legacy users.visibility_scope must be dropped once its value has been backfilled"
        )
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_visibility_scope_backfill_leaves_null_when_telegram_id_missing_from_users():
    """telegram_id present only in staff, never registered as a User (the
    Artem scenario: resolved purely through the staff table for clinic lookup)
    -- there is nothing to migrate, visibility_scope must stay NULL rather
    than the backfill raising."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        await connection.execute("""
            CREATE TABLE users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER UNIQUE,
                visibility_scope TEXT DEFAULT NULL
            )
        """)
        await connection.commit()

        staff_repo = StaffRepository(connection)
        await staff_repo.init()

        staff = await staff_repo.get_staff(685889801)
        assert staff.visibility_scope is None

        cursor = await connection.execute("PRAGMA table_info(users)")
        users_columns = {row[1] for row in await cursor.fetchall()}
        assert "visibility_scope" not in users_columns
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_visibility_scope_source_column_dropped_even_if_staff_already_migrated():
    """Real-world scenario hit in production: a prior deploy already ran the
    add-column+backfill block (staff.visibility_scope already exists with a
    real value), so that guard is skipped on this run -- but users.visibility_scope
    is still physically lingering and must be dropped on its own, independent
    guard, not only as a side effect of the first-time backfill."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        await connection.execute("""
            CREATE TABLE users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER UNIQUE,
                visibility_scope TEXT DEFAULT NULL
            )
        """)
        await connection.execute(
            "INSERT INTO users(telegram_user_id, visibility_scope) VALUES (?, ?)",
            (685889801, "clinic"),
        )
        # Simulate staff already having gone through the add-column+backfill
        # step in an earlier deploy, by creating it with the column already
        # present (so init()'s "not in columns" guard for staff is False).
        await connection.execute("""
            CREATE TABLE staff(
                telegram_user_id INTEGER PRIMARY KEY,
                clinic_id INTEGER NOT NULL,
                visibility_scope TEXT DEFAULT NULL
            )
        """)
        await connection.execute(
            "INSERT INTO staff(telegram_user_id, clinic_id, visibility_scope) VALUES (?, 1, 'clinic')",
            (685889801,),
        )
        await connection.commit()

        staff_repo = StaffRepository(connection)
        await staff_repo.init()

        staff = await staff_repo.get_staff(685889801)
        assert staff.visibility_scope == "clinic"

        cursor = await connection.execute("PRAGMA table_info(users)")
        users_columns = {row[1] for row in await cursor.fetchall()}
        assert "visibility_scope" not in users_columns
    finally:
        await connection.close()
