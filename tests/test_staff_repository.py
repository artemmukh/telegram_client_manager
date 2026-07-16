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
    finally:
        await connection.close()
