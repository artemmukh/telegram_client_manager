from pathlib import Path
import bot.models.user
import bot.models.record
import aiosqlite


class RecordDataBase:
    def __init__(self, path: str) -> None:
        self.path = Path("database.db")



    async def init_record(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute("""
            CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
            telegram_user_id INTEGER UNIQUE NOT NULL, 
            date_time TEXT NOT NULL,
            description TEXT NOT NULL,
            recommendation TEXT,
            price INTEGER DEFAULT 0 NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
            """)
            await connection.commit()

        async def get_records_by_name(self, full_name: str) -> list[bot.models.record.Record]:
            async with aiosqlite.connect(self.path) as connection:
                cursor = await connection.execute(
                    "SELECT * FROM records WHERE full_name = ?", (full_name)
                )
                records = await cursor.fetchall()
                return records

        async def get_records_by_phone(self, phone: str) -> list[bot.models.record.Record]:
            async with aiosqlite.connect(self.path) as connection:
                cursor = await connection.execute(
                    "SELECT * FROM records WHERE phone = ?", (phone)
                )
                records = await cursor.fetchall()
                return records

        async def create_record(self, record: bot.models.record.Record) -> None:
            async with aiosqlite.connect(self.path) as connection:
                cursor = await connection.execute(
                    """INSERT INTO records 
                    (
                    user_id,
                    date_time,
                    description,
                    recommendation,
                    price,
                    status
                    )
                    SELECT
                        id,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?
                    FROM users
                    WHERE telegram_id = ?;"""
                )
                await connection.commit()

        async def update_record(self, telegram_id: int, record: bot.models.record.Record) -> None:
            async with aiosqlite.connect(self.path) as connection:
                cursor = await connection.execute(
                    """UPDATE records SET 
                    date_time = ?,
                    description = ?,
                    recommendation = ?,
                    price = ?,
                    status = ?
                    WHERE id = ?;"""
                )

