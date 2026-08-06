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
        # Staff seeding now resolves clinic_id by clinic token (not a
        # hardcoded numeric id), so the seed clinic must actually exist.
        # 685889801 is seeded under the "Зуб Мудрости" clinic token.
        await connection.execute(
            "INSERT INTO clinics(id, name, token) VALUES (1, 'Test Clinic', 'x7A92JdPkLmQe81')"
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
        await staff_repo.init("zb")

        staff = await staff_repo.get_staff(685889801)
        assert staff.visibility_scope == "clinic"
        assert staff.is_doctor is False

        seeded_staff = await staff_repo.get_staff_by_clinic_id(1)
        seeded_by_id = {member.telegram_user_id: member for member in seeded_staff}
        assert seeded_by_id[226655040].visibility_scope == "own"
        assert seeded_by_id[226655040].is_doctor is True
        assert seeded_by_id[37470594].visibility_scope == "own"
        assert seeded_by_id[37470594].is_doctor is True

        cursor = await connection.execute("PRAGMA table_info(users)")
        users_columns = {row[1] for row in await cursor.fetchall()}
        assert "visibility_scope" not in users_columns, (
            "legacy users.visibility_scope must be dropped once its value has been backfilled"
        )
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_seed_sets_visibility_scope_when_telegram_id_missing_from_users():
    """telegram_id present only in staff, never registered as a User (the
    Artem scenario: resolved purely through the staff table for clinic lookup)
    -- there is nothing to backfill, but the explicit seed configuration still
    sets the staff member's notification visibility."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute(
            "CREATE TABLE clinics(id INTEGER PRIMARY KEY, name TEXT, token TEXT)"
        )
        # Staff seeding now resolves clinic_id by clinic token (not a
        # hardcoded numeric id), so the seed clinic must actually exist.
        # 685889801 is seeded under the "Зуб Мудрости" clinic token.
        await connection.execute(
            "INSERT INTO clinics(id, name, token) VALUES (1, 'Test Clinic', 'x7A92JdPkLmQe81')"
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
        await staff_repo.init("zb")

        staff = await staff_repo.get_staff(685889801)
        assert staff.visibility_scope == "clinic"

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
        await staff_repo.init("zb")

        staff = await staff_repo.get_staff(685889801)
        assert staff.visibility_scope == "clinic"
        assert staff.is_doctor is False

        cursor = await connection.execute("PRAGMA table_info(users)")
        users_columns = {row[1] for row in await cursor.fetchall()}
        assert "visibility_scope" not in users_columns
    finally:
        await connection.close()
