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

        await self.connection.commit()

    async def add_staff(self, staff: Staff) -> None:
        await self.connection.execute(
            """
            INSERT INTO staff(
                telegram_user_id,
                clinic_id
            )
            VALUES (?, ?)
            """,
            (
                staff.telegram_user_id,
                staff.clinic_id,
            )
        )
        await self.connection.commit()

    async def remove_staff(self, telegram_user_id: int) -> None:
        await self.connection.execute(
            """
            DELETE FROM staff
            WHERE telegram_user_id = ?
            """,
            (telegram_user_id,)
        )
        await self.connection.commit()

    async def get_staff(self, telegram_user_id: int) -> Staff | None:
        cursor = await self.connection.execute(
            """
            SELECT
                telegram_user_id,
                clinic_id
            FROM staff
            WHERE telegram_user_id = ?
            """,
            (telegram_user_id,)
        )

        return self._row_to_staff(await cursor.fetchone())

    async def is_staff(self, telegram_user_id: int) -> bool:
        cursor = await self.connection.execute(
            """
            SELECT 1
            FROM staff
            WHERE telegram_user_id = ?
            """,
            (telegram_user_id,)
        )

        return await cursor.fetchone() is not None

    def _row_to_staff(self, row) -> Staff | None:
        if row is None:
            return None

        return Staff(
            telegram_user_id=row[0],
            clinic_id=row[1],
        )