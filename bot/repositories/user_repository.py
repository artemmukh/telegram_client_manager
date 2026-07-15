import aiosqlite

from bot.exceptions.user_exceptions import UserAlreadyExistsError, UserNotFoundError
from bot.models.user import User
from bot.utils.role import Role

USER_SELECT = """
SELECT
    u.id,
    u.telegram_user_id,
    u.full_name,
    u.phone,
    u.clinic_id,
    c.name AS clinic_name,
    u.role,
    u.reminder_24h,
    u.reminder_2h,
    u.pending_full_name,
    u.created_at,
    u.visibility_scope
FROM users u
LEFT JOIN clinics c
ON u.clinic_id = c.id
"""

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
                clinic_id INTEGER DEFAULT NULL,
                role TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reminder_24h INTEGER DEFAULT 1,
                reminder_2h INTEGER DEFAULT 1,
                pending_full_name TEXT DEFAULT NULL,
                visibility_scope TEXT DEFAULT NULL,

                FOREIGN KEY(clinic_id) REFERENCES clinics(id) ON DELETE CASCADE)
        """)

        cursor = await self.connection.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "reminder_24h" not in columns:
            await self.connection.execute(
                "ALTER TABLE users ADD COLUMN reminder_24h INTEGER DEFAULT 1"
            )

        if "reminder_2h" not in columns:
            await self.connection.execute(
                "ALTER TABLE users ADD COLUMN reminder_2h INTEGER DEFAULT 1"
            )

        if "pending_full_name" not in columns:
            await self.connection.execute(
                "ALTER TABLE users ADD COLUMN pending_full_name TEXT DEFAULT NULL"
            )

        if "visibility_scope" not in columns:
            await self.connection.execute(
                "ALTER TABLE users ADD COLUMN visibility_scope TEXT DEFAULT NULL"
            )

        await self.connection.commit()

    async def get_user_by_telegram_id(self, telegram_user_id: int) -> User | None:
        cursor = await self.connection.execute(
            USER_SELECT + """
            WHERE u.telegram_user_id = ?
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
                    clinic_id,
                    role,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user.telegram_user_id,
                    user.full_name,
                    user.phone,
                    user.clinic_id,
                    user.role.value,
                    user.created_at,
                )
            )
            await self.connection.commit()

        except aiosqlite.IntegrityError:
            raise UserAlreadyExistsError()

    async def get_staff_users_by_clinic_id(self, clinic_id: int) -> list[User]:
        cursor = await self.connection.execute(
            USER_SELECT + """
            WHERE u.role = 'admin'
            AND u.clinic_id = ?
            ORDER BY u.full_name, u.id
            """,
            (clinic_id,)
        )
        rows = await cursor.fetchall()

        return [self._row_to_user(row) for row in rows]

    async def get_clients_by_name(self, full_name: str) -> list[User]:
        parts = full_name.strip().title().split()
        if not parts:
            return []

        conditions = " OR ".join(["full_name LIKE ?"] * len(parts))
        params = [f"%{part}%" for part in parts]

        sql = USER_SELECT + f"""
        WHERE u.role = 'client'
        AND ({conditions})
        ORDER BY u.full_name, u.id
        """

        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()

        return [self._row_to_user(row) for row in rows]

    async def get_client_by_phone(self, phone: str) -> User | None:
        cursor = await self.connection.execute(
            USER_SELECT + """
            WHERE u.role = 'client'
            AND u.phone = ?
            """,
            (phone,)
        )
        return self._row_to_user(await cursor.fetchone())

    async def update_client(self, user_id: int, user: User) -> User | None:
        await self.connection.execute(
            """
            UPDATE users
            SET full_name = ?,
                phone     = ?,
                role      = ?
            WHERE id = ?
            """,
            (
                user.full_name,
                user.phone,
                user.role.value,
                user_id
            )
        )
        await self.connection.commit()

        return await self.get_client_by_id(user_id)

    async def update_reminder_preferences(self, user_id: int, reminder_24h: bool, reminder_2h: bool) -> None:
        await self.connection.execute(
            "UPDATE users SET reminder_24h = ?, reminder_2h = ? WHERE id = ?",
            (int(reminder_24h), int(reminder_2h), user_id),
        )
        await self.connection.commit()

    async def set_pending_full_name(self, user_id: int, new_full_name: str) -> None:
        await self.connection.execute(
            "UPDATE users SET pending_full_name = ? WHERE id = ?",
            (new_full_name, user_id),
        )
        await self.connection.commit()

    async def resolve_pending_full_name(self, user_id: int, approve: bool) -> User | None:
        # The "pending_full_name IS NOT NULL" guard makes this update a compare-and-set:
        # it only applies when a pending request still exists, so a request already
        # resolved (or never made) cannot be resolved twice.
        if approve:
            sql = """
                UPDATE users
                SET full_name = pending_full_name,
                    pending_full_name = NULL
                WHERE id = ? AND pending_full_name IS NOT NULL
            """
        else:
            sql = """
                UPDATE users
                SET pending_full_name = NULL
                WHERE id = ? AND pending_full_name IS NOT NULL
            """

        cursor = await self.connection.execute(sql, (user_id,))
        await self.connection.commit()

        if cursor.rowcount == 0:
            return None

        return await self.get_user_by_id(user_id)

    async def update_user_telegram_id(self, user_id: int, telegram_user_id: int) -> None:
        await self.connection.execute(
            """
            UPDATE users
            SET telegram_user_id = ?
            WHERE id = ?
            """,
            (telegram_user_id, user_id),
        )
        await self.connection.commit()

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
            USER_SELECT + """
            WHERE u.role = 'client'
            AND u.id = ?
            """,
            (user_id,)
        )
        return self._row_to_user(await cursor.fetchone())

    async def get_user_by_id(self, user_id: int) -> User | None:
        cursor = await self.connection.execute(
            USER_SELECT + """
            WHERE u.id = ?
            """,
            (user_id,)
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
            clinic_id=row[4],
            clinic_name=row[5],
            role=Role(row[6]) if row[6] else None,
            reminder_24h=bool(row[7]),
            reminder_2h=bool(row[8]),
            pending_full_name=row[9],
            created_at=row[10],
            visibility_scope=row[11],
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

    async def get_clients_page(
        self, page: int, per_page: int = 10
    ) -> list[User]:
        """Получить страницу клиентов (все клиенты)"""
        offset = (page - 1) * per_page
        cursor = await self.connection.execute(
            USER_SELECT + """
            WHERE u.role = 'client'
            ORDER BY u.full_name, u.id
            LIMIT ? OFFSET ?
            """,
            (per_page, offset)
        )
        rows = await cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

    async def count_all_clients(self) -> int:
        """Получить общее количество клиентов"""
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'client'"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_clients_by_name_page(
        self, full_name: str, page: int, per_page: int = 10
    ) -> list[User]:
        """Получить страницу результатов поиска по имени"""
        parts = full_name.strip().title().split()
        if not parts:
            return []

        conditions = " OR ".join(["full_name LIKE ?"] * len(parts))
        params = [f"%{part}%" for part in parts]

        offset = (page - 1) * per_page

        sql = USER_SELECT + f"""
        WHERE u.role = 'client'
        AND ({conditions})
        ORDER BY u.full_name, u.id
        LIMIT ? OFFSET ?
        """
        params.extend([per_page, offset])

        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

    async def count_clients_by_name(self, full_name: str) -> int:
        """Получить количество результатов поиска по имени"""
        parts = full_name.strip().title().split()
        if not parts:
            return 0

        conditions = " OR ".join(["full_name LIKE ?"] * len(parts))
        params = [f"%{part}%" for part in parts]

        sql = f"SELECT COUNT(*) FROM users WHERE role = 'client' AND ({conditions})"
        cursor = await self.connection.execute(sql, params)
        row = await cursor.fetchone()
        return row[0] if row else 0