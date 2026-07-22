import aiosqlite

from bot.models.user_settings import UserSettings


class UserSettingsRepository:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection

    async def init(self) -> None:
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS user_settings(
                user_id INTEGER PRIMARY KEY,
                reminder_24h INTEGER NOT NULL DEFAULT 1,
                reminder_2h  INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        cursor = await self.connection.execute("PRAGMA table_info(users)")
        users_columns = {row[1] for row in await cursor.fetchall()}

        if "reminder_24h" in users_columns and "reminder_2h" in users_columns:
            await self.connection.execute("""
                INSERT OR IGNORE INTO user_settings(user_id, reminder_24h, reminder_2h)
                SELECT id, reminder_24h, reminder_2h FROM users
            """)
            await self.connection.execute("ALTER TABLE users DROP COLUMN reminder_24h")
            await self.connection.execute("ALTER TABLE users DROP COLUMN reminder_2h")

        await self.connection.commit()

    async def upsert(self, user_id: int, reminder_24h: bool, reminder_2h: bool) -> None:
        await self.connection.execute(
            """
            INSERT INTO user_settings(user_id, reminder_24h, reminder_2h)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                reminder_24h = excluded.reminder_24h,
                reminder_2h = excluded.reminder_2h
            """,
            (user_id, int(reminder_24h), int(reminder_2h)),
        )
        await self.connection.commit()

    async def get_by_user_id(self, user_id: int) -> UserSettings | None:
        cursor = await self.connection.execute(
            "SELECT user_id, reminder_24h, reminder_2h FROM user_settings WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        return UserSettings(
            user_id=row[0],
            reminder_24h=bool(row[1]),
            reminder_2h=bool(row[2]),
        )
