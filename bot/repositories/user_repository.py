from pathlib import Path
import aiosqlite

from bot.exceptions.user_exceptions import UserAlreadyExistsError, UserNotFoundError
from bot.models.user import User


class UserRepository:
    def __init__(self, path: str):
        self.path = Path(path)

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.path) as connection:
            await connection.execute("PRAGMA foreign_keys = ON")

            await connection.execute("""
                CREATE TABLE IF NOT EXISTS users(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT UNIQUE NOT NULL,
                    role TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
            """)

            await connection.commit()


    async def get_user_by_telegram_id(self, telegram_user_id: int) -> User | None:

        async with aiosqlite.connect(self.path) as connection:

            cursor = await connection.execute(
                """
                SELECT
                    id,
                    telegram_user_id,
                    full_name,
                    phone,
                    role
                FROM users
                WHERE telegram_user_id = ?
                """,
                (telegram_user_id,)
            )
            return self._row_to_user(await cursor.fetchone())

    async def create_user(self, user: User) -> None:

        async with aiosqlite.connect(self.path) as connection:

            try:

                await connection.execute(
                    """
                    INSERT INTO users(
                        telegram_user_id,
                        full_name,
                        phone,
                        role
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        user.telegram_user_id,
                        user.full_name,
                        user.phone,
                        user.role.value,
                    )
                )

                await connection.commit()

            except aiosqlite.IntegrityError:
                raise UserAlreadyExistsError()

    async def get_clients_by_name(self, full_name: str) -> list[User] | None:
        query = f"%{full_name.strip()}%"
        async with aiosqlite.connect(self.path) as connection:
            cursor = await connection.execute(
                """
                SELECT
                    id,
                    telegram_user_id,
                    full_name,
                    phone,
                    role
                FROM users
                WHERE role = 'client' AND full_name LIKE ? ORDER BY full_name
                """,
                (query,),
            )

            rows = await cursor.fetchall()

        return [self._row_to_user(row) for row in rows]


    async def get_all_clients(self) -> list[User] | None:

        async with aiosqlite.connect(self.path) as connection:

            cursor = await connection.execute(
                """
                SELECT * FROM users WHERE role = 'client' ORDER BY full_name
                """
            )

            rows = await cursor.fetchall()
            return [self._row_to_user(row) for row in rows]






    async def get_client_by_phone(self, phone: str) -> User | None:

        async with aiosqlite.connect(self.path) as connection:

            cursor = await connection.execute(
                """
                SELECT
                    id,
                    telegram_user_id,
                    full_name,
                    phone,
                    role
                FROM users
                WHERE role = 'client' AND phone = ? ORDER BY full_name
                """,
                (phone,)
            )
            return self._row_to_user(await cursor.fetchone())

    async def update_client(self, user_id: int, user: User) -> User | None:

        async with aiosqlite.connect(self.path) as connection:

            cursor = await connection.execute(
                """
                UPDATE users
                SET
                    full_name = ?,
                    phone = ?,
                    role = ?
                WHERE id = ?
                """,
                (
                    user.full_name,
                    user.phone,
                    user.role.value,
                    user_id
                )
            )

            await connection.commit()

            return self._row_to_user(await cursor.fetchone())



    async def delete_client(self, user_id: int) -> None:

        async with aiosqlite.connect(self.path) as connection:

            await connection.execute(
                """
                DELETE FROM users
                WHERE id = ? AND role = 'client'
                """,
                (user_id,)
            )

            await connection.commit()


    async def get_client_by_id(self, user_id: int) -> User | None:

        async with aiosqlite.connect(self.path) as connection:

            cursor = await connection.execute(
                """
                SELECT * FROM users WHERE role = 'client' AND id= ?
                """, (user_id,)
            )
            return self._row_to_user(
                await cursor.fetchone()
            )

    async def user_exists(self, telegram_user_id: int) -> bool:

        async with aiosqlite.connect(self.path) as connection:

            cursor = await connection.execute(

                """
                SELECT 1 FROM users WHERE telegram_user_id = ?
                """, (telegram_user_id,))

            return await cursor.fetchone() is not None




    def _row_to_user(self, row) -> User | None:  # here SELECT does not depend on the number of columns
        # so we can return User directly through 3 methods (DRY)
        if row is None:
            return None

        return User(
            ID=row[0],
            telegram_user_id=row[1],
            full_name=row[2],
            phone=row[3],
            role=row[4],
        )

    async def phone_exists(self, phone: str) -> bool:

        async with aiosqlite.connect(self.path) as connection:

            cursor = await connection.execute(

                """
                SELECT 1 FROM users WHERE phone = ?
                """, (phone,))

            return await cursor.fetchone() is not None



    async def get_user_role(self, telegram_user_id: int) -> str:

        async with aiosqlite.connect(self.path) as connection:

            cursor = await connection.execute(
                """
                SELECT role FROM users WHERE telegram_user_id = ?
                """, (telegram_user_id,)
            )
            row = await cursor.fetchone()
            if row:
                return row[0]
            raise UserNotFoundError("User not found")
