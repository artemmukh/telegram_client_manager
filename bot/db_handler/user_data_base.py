from pathlib import Path
import bot.models.user
import bot.models.record
import aiosqlite


class UserDataBase:
    def __init__(self, path: str) -> None:
        self.path = Path("database.db")



    async def init_client(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as connection:
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                telegram_id INTEGER UNIQUE,
                full_name TEXT NOT NULL,
                phone TEXT UNIQUE NOT NULL, 
                role TEXT DEFAULT 'client' NOT NULL,
                is_registered BOOLEAN DEFAULT FALSE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                """)
            await connection.commit()




    async def get_user_by_telegram_id(self, telegram_id: int):
        async with aiosqlite.connect(self.path) as connection:
            cursor = await connection.execute(
                "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
            )
            user = await cursor.fetchone()
            return user

    async def create_user(
            self, user: bot.models.user.User
    ):
        async with aiosqlite.connect(self.path) as connection:
            cursor = await connection.execute(
                """
                INSERT INTO users (full_name, phone, role, is_registered)"""
            )
            await connection.commit()


    async def search_by_name(self, name: str):
        async with aiosqlite.connect(self.path) as connection:
            cursor = await connection.execute(
                "SELECT * FROM users WHERE full_name = ?", (name,)
            )
            user = await cursor.fetchone()
            return user

    async def search_by_phone(self, phone: str):
        async with aiosqlite.connect(self.path) as connection:
            cursor = await connection.execute(
                "SELECT * FROM users WHERE phone = ?", (phone,)
            )
            user = await cursor.fetchone()
            return user


    async def delete_user(self, telegram_id: int):
        async with aiosqlite.connect(self.path) as connection:
            cursor = await connection.execute(
                "DELETE FROM users WHERE telegram_id = ?", (telegram_id,)
            )
            await connection.commit()

    async def update_user(self, telegram_id: int, user: bot.models.user.User):
        async with aiosqlite.connect(self.path) as connection:
            cursor = await connection.execute(
                "UPDATE users SET full_name = ?, phone = ? WHERE telegram_id = ?",
                (user.full_name, user.phone, telegram_id)
            )
            await connection.commit()

