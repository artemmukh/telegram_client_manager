
from pathlib import Path
import aiosqlite

from bot.models.record import Record


class RecordRepository:
    def __init__(self, path: str):
        self.path = Path(path)

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.path) as connection:
            await connection.execute("PRAGMA foreign_keys = ON")

            await connection.execute("""
                CREATE TABLE IF NOT EXISTS records(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    date_time TIMESTAMP NOT NULL,
                    description TEXT,
                    recommendation TEXT,
                    price REAL,
                    status TEXT,

                    FOREIGN KEY(user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE)
            """)

            await connection.commit()

    async def get_record_by_id(
        self,
        record_id: int
    ) -> Record | None:
        async with aiosqlite.connect(self.path) as connection:

            cursor = await connection.execute(
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

    async def get_records_by_user_id(
        self,
        user_id: int
    ) -> list[Record]:

        async with aiosqlite.connect(self.path) as connection:

            cursor = await connection.execute(
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

    async def get_records_by_telegram_id(
        self,
        telegram_user_id: int
    ) -> list[Record]:

        async with aiosqlite.connect(self.path) as connection:

            cursor = await connection.execute(
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

    async def create_record(
        self,
        record: Record
    ) -> None:

        async with aiosqlite.connect(self.path) as connection:

            await connection.execute(
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

            await connection.commit()

    async def update_record(
        self,
        record_id: int,
        record: Record
    ) -> None:

        async with aiosqlite.connect(self.path) as connection:

            await connection.execute(
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

            await connection.commit()

    async def delete_record(
        self,
        record_id: int
    ) -> None:

        async with aiosqlite.connect(self.path) as connection:

            await connection.execute(
                """
                DELETE FROM records
                WHERE id = ?
                """,
                (record_id,)
            )

            await connection.commit()

    async def record_exists(
        self,
        record_id: int
    ) -> bool:

        async with aiosqlite.connect(self.path) as connection:

            cursor = await connection.execute(
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
            primary_id=row[0],
            user_id=row[1],
            date_time=row[2],
            description=row[3],
            recommendation=row[4],
            price=row[5],
            status=row[6]
        )