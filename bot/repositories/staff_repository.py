import aiosqlite


from bot.models.staff import Staff


class StaffRepository:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection

    async def init(self) -> None:
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS staff(
                telegram_user_id INTEGER PRIMARY KEY,
                clinic_id INTEGER NOT NULL,

                FOREIGN KEY(clinic_id)
                    REFERENCES clinics(id)
                    ON DELETE CASCADE
            )
        """)

        await self.connection.execute("""
        INSERT OR IGNORE INTO staff (
                    telegram_user_id,
                    clinic_id)
            
            
                    VALUES
                    (685889801, 1),
                    (226655040, 1),
                    (37470594, 1);
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

        # Drop the now-redundant source column from users, independent of the
        # backfill guard above: on a database that already ran the backfill in
        # a prior deploy (staff.visibility_scope already exists), the block
        # above is skipped entirely, but users.visibility_scope may still be
        # lingering and needs its own check to be cleaned up.
        users_cursor = await self.connection.execute("PRAGMA table_info(users)")
        users_columns = {row[1] for row in await users_cursor.fetchall()}

        if "visibility_scope" in users_columns:
            await self.connection.execute("ALTER TABLE users DROP COLUMN visibility_scope")

        await self.connection.commit()

    async def get_staff(self, telegram_user_id: int) -> Staff | None:
        cursor = await self.connection.execute(
            """
            SELECT
                telegram_user_id,
                clinic_id,
                visibility_scope
            FROM staff
            WHERE telegram_user_id = ?
            """,
            (telegram_user_id,)
        )

        return self._row_to_staff(await cursor.fetchone())

    def _row_to_staff(self, row) -> Staff | None:
        if row is None:
            return None

        return Staff(
            telegram_user_id=row[0],
            clinic_id=row[1],
            visibility_scope=row[2],
        )