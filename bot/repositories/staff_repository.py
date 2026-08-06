import aiosqlite


from bot.config.clinic_instances import (
    CLINIC_SEED_BY_INSTANCE,
    STAFF_SEED_BY_INSTANCE,
    STAFF_VISIBILITY_SCOPE_BY_INSTANCE,
)
from bot.models.staff import Staff


class StaffRepository:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection

    async def init(self, instance: str) -> None:
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS staff(
                telegram_user_id INTEGER PRIMARY KEY,
                clinic_id INTEGER NOT NULL,
                visibility_scope TEXT DEFAULT NULL,
                is_doctor INTEGER NOT NULL DEFAULT 1,

                FOREIGN KEY(clinic_id)
                    REFERENCES clinics(id)
                    ON DELETE CASCADE
            )
        """)

        cursor = await self.connection.execute("PRAGMA table_info(staff)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "visibility_scope" not in columns:
            await self.connection.execute(
                "ALTER TABLE staff ADD COLUMN visibility_scope TEXT DEFAULT NULL"
            )

            users_cursor = await self.connection.execute("PRAGMA table_info(users)")
            users_columns = {row[1] for row in await users_cursor.fetchall()}

            if "visibility_scope" in users_columns:
                await self.connection.execute("""
                    UPDATE staff SET visibility_scope = (
                        SELECT u.visibility_scope FROM users u
                        WHERE u.telegram_user_id = staff.telegram_user_id
                    )
                    WHERE EXISTS (
                        SELECT 1 FROM users u WHERE u.telegram_user_id = staff.telegram_user_id
                    )
                """)

        if "is_doctor" not in columns:
            await self.connection.execute(
                "ALTER TABLE staff ADD COLUMN is_doctor INTEGER NOT NULL DEFAULT 1"
            )
            await self.connection.execute(
                "UPDATE staff SET is_doctor = CASE WHEN visibility_scope = 'clinic' THEN 0 ELSE 1 END"
            )

        # Drop the now-redundant source column from users, independent of the
        # backfill guard above: on a database that already ran the backfill in
        # a prior deploy (staff.visibility_scope already exists), the block
        # above is skipped entirely, but users.visibility_scope may still be
        # lingering and needs its own check to be cleaned up.
        users_cursor = await self.connection.execute("PRAGMA table_info(users)")
        users_columns = {row[1] for row in await users_cursor.fetchall()}

        if "visibility_scope" in users_columns:
            await self.connection.execute("ALTER TABLE users DROP COLUMN visibility_scope")

        # Each instance now runs its own dedicated database (one clinic per
        # DB), so only that instance's own staff are seeded here.
        clinic_token = CLINIC_SEED_BY_INSTANCE[instance]["token"]
        await self._seed_staff_by_clinic_token(
            clinic_token,
            STAFF_SEED_BY_INSTANCE[instance],
            STAFF_VISIBILITY_SCOPE_BY_INSTANCE[instance],
        )

        await self.connection.commit()

    async def _seed_staff_by_clinic_token(
        self,
        clinic_token: str,
        telegram_user_ids: list[int],
        visibility_scopes: dict[int, str],
    ) -> None:
        # Seed telegram ids resolved by clinic token rather than a hardcoded
        # clinic_id: clinics.id is AUTOINCREMENT, so the numeric id a given
        # clinic ends up with depends on insert history (migrations, backups,
        # restores) and isn't guaranteed to match the order clinics were
        # first added in source. A hardcoded id can point at the wrong clinic
        # or, if that id doesn't exist yet, trip the FOREIGN KEY constraint
        # (INSERT OR IGNORE does not suppress FK violations in SQLite).
        cursor = await self.connection.execute(
            "SELECT id FROM clinics WHERE token = ?", (clinic_token,)
        )
        row = await cursor.fetchone()

        if row is None:
            return

        clinic_id = row[0]

        await self.connection.executemany(
            """
            INSERT OR IGNORE INTO staff
                (telegram_user_id, clinic_id, visibility_scope, is_doctor)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    telegram_user_id,
                    clinic_id,
                    visibility_scopes[telegram_user_id],
                    int(visibility_scopes[telegram_user_id] != "clinic"),
                )
                for telegram_user_id in telegram_user_ids
            ],
        )

    async def get_staff(self, telegram_user_id: int) -> Staff | None:
        cursor = await self.connection.execute(
            """
            SELECT
                telegram_user_id,
                clinic_id,
                visibility_scope,
                is_doctor
            FROM staff
            WHERE telegram_user_id = ?
            """,
            (telegram_user_id,)
        )

        return self._row_to_staff(await cursor.fetchone())

    async def get_staff_by_clinic_id(self, clinic_id: int) -> list[Staff]:
        cursor = await self.connection.execute(
            """
            SELECT telegram_user_id, clinic_id, visibility_scope, is_doctor
            FROM staff
            WHERE clinic_id = ?
            """,
            (clinic_id,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_staff(row) for row in rows]

    def _row_to_staff(self, row) -> Staff | None:
        if row is None:
            return None

        return Staff(
            telegram_user_id=row[0],
            clinic_id=row[1],
            visibility_scope=row[2],
            is_doctor=bool(row[3]),
        )
