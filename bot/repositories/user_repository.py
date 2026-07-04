import aiosqlite

from bot.exceptions.user_exceptions import UserAlreadyExistsError, UserNotFoundError
from bot.models.user import User


class UserRepository:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection

    async def init(self) -> None:
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER UNIQUE,
                full_name TEXT NOT NULL,
                phone TEXT UNIQUE NOT NULL,
                role TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
        """)
        await self.connection.commit()

    async def get_user_by_telegram_id(self, telegram_user_id: int) -> User | None:
        cursor = await self.connection.execute(
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
        try:
            await self.connection.execute(
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
            await self.connection.commit()

        except aiosqlite.IntegrityError:
            raise UserAlreadyExistsError()

    async def get_clients_by_name(self, full_name: str) -> list[User]:
        parts = full_name.strip().title().split()

        conditions = " OR ".join(["full_name LIKE ?"] * len(parts))
        params = [f"%{part}%" for part in parts]

        sql = f"""
        SELECT
            id,
            telegram_user_id,
            full_name,
            phone,
            role
        FROM users
        WHERE role = 'client'
          AND ({conditions})
        ORDER BY full_name
        """

        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()

        return [self._row_to_user(row) for row in rows]

    async def get_all_clients(self) -> list[User] | None:
        cursor = await self.connection.execute(
            """
            SELECT * FROM users WHERE role = 'client' ORDER BY full_name
            """
        )
        rows = await cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

    async def get_client_by_phone(self, phone: str) -> User | None:
        cursor = await self.connection.execute(
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
        cursor = await self.connection.execute(
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
                user.role,
                user_id
            )
        )
        await self.connection.commit()

        return self._row_to_user(await cursor.fetchone())

    async def delete_client(self, user_id: int) -> None:
        await self.connection.execute(
            """
            DELETE FROM users
            WHERE id = ? AND role = 'client'
            """,
            (user_id,)
        )
        await self.connection.commit()

    async def get_client_by_id(self, user_id: int) -> User | None:
        cursor = await self.connection.execute(
            """
            SELECT * FROM users WHERE role = 'client' AND id = ?
            """, (user_id,)
        )
        return self._row_to_user(await cursor.fetchone())

    async def user_exists(self, telegram_user_id: int) -> bool:
        cursor = await self.connection.execute(
            """
            SELECT 1 FROM users WHERE telegram_user_id = ?
            """, (telegram_user_id,)
        )
        return await cursor.fetchone() is not None

    def _row_to_user(self, row) -> User | None:
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
        cursor = await self.connection.execute(
            """
            SELECT 1 FROM users WHERE phone = ?
            """, (phone,)
        )
        return await cursor.fetchone() is not None

    async def get_user_role(self, telegram_user_id: int) -> str:
        cursor = await self.connection.execute(
            """
            SELECT role FROM users WHERE telegram_user_id = ?
            """, (telegram_user_id,)
        )
        row = await cursor.fetchone()
        if row:
            return row[0]
        raise UserNotFoundError("User not found")