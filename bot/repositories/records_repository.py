import aiosqlite

from bot.models.record import Record


class RecordRepository:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection

    async def init(self) -> None:
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS records(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clinic_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                date_time TIMESTAMP NOT NULL,
                diagnose TEXT DEFAULT NULL,
                description TEXT DEFAULT NULL,
                recommendation TEXT DEFAULT NULL,
                price REAL,
                status TEXT,
                
                FOREIGN KEY(user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(clinic_id) REFERENCES clinics(id) ON DELETE CASCADE)
        """)
        await self.connection.commit()

    async def get_record_by_id(self, record_id: int) -> Record | None:
        cursor = await self.connection.execute(
            """
            SELECT
                id,
                user_id,
                date_time,
                description,
                recommendation,
                price,
                status
            FROM records
            WHERE id = ?
            """,
            (record_id,)
        )
        return self._row_to_record(await cursor.fetchone())

    async def get_records_by_user_id(self, user_id: int) -> list[Record]:
        cursor = await self.connection.execute(
            """
            SELECT
                id,
                user_id,
                date_time,
                description,
                recommendation,
                price,
                status
            FROM records
            WHERE user_id = ?
            """,
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    async def get_records_by_telegram_id(self, telegram_user_id: int) -> list[Record]:
        cursor = await self.connection.execute(
            """
            SELECT
                r.id,
                r.user_id,
                r.date_time,
                r.description,
                r.recommendation,
                r.price,
                r.status
            FROM records as r
            JOIN users as u ON u.id = r.user_id
            WHERE u.telegram_user_id = ?
            """,
            (telegram_user_id,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    async def create_record(self, record: Record) -> None:
        await self.connection.execute(
            """
            INSERT INTO records(
                user_id,
                date_time,
                description,
                recommendation,
                price,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record.user_id,
                record.date_time,
                record.description,
                record.recommendation,
                record.price,
                record.status
            )
        )
        await self.connection.commit()

    async def update_record(self, record_id: int, record: Record) -> None:
        await self.connection.execute(
            """
            UPDATE records
            SET
                date_time = ?,
                description = ?,
                recommendation = ?,
                price = ?,
                status = ?
            WHERE id = ?
            """,
            (
                record.date_time,
                record.description,
                record.recommendation,
                record.price,
                record.status,
                record_id
            )
        )
        await self.connection.commit()

    async def delete_record(self, record_id: int) -> None:
        await self.connection.execute(
            """
            DELETE FROM records
            WHERE id = ?
            """,
            (record_id,)
        )
        await self.connection.commit()

    async def record_exists(self, record_id: int) -> bool:
        cursor = await self.connection.execute(
            """
            SELECT 1
            FROM records
            WHERE id = ?
            """,
            (record_id,)
        )
        return await cursor.fetchone() is not None

    def _row_to_record(self, row) -> Record | None:
        if row is None:
            return None
        return Record(
            id=row[0],
            clinic_id=row[1],
            user_id=row[2],
            date_time=row[3],
            description=row[4],
            recommendation=row[5],
            price=row[6],
            status=row[7]
        )