import aiosqlite

from bot.exceptions.user_exceptions import (
    PHONE_ALREADY_EXISTS_MESSAGE,
    PhoneAlreadyExistsError,
    UserAlreadyExistsError,
    UserNotFoundError,
    ValidationError,
)
from bot.models.user import User
from bot.utils.role import Role

USER_SELECT = """
SELECT
    u.id,
    u.telegram_user_id,
    u.full_name,
    u.gender,
    u.birth_date,
    u.phone,
    u.clinic_id,
    c.name AS clinic_name,
    u.role,
    COALESCE(us.reminder_24h, 1),
    COALESCE(us.reminder_2h, 1),
    u.pending_full_name,
    u.created_at
FROM users u
LEFT JOIN clinics c
ON u.clinic_id = c.id
LEFT JOIN user_settings us
ON us.user_id = u.id
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
                gender TEXT DEFAULT NULL,
                birth_date TEXT DEFAULT NULL,
                phone TEXT UNIQUE NOT NULL,
                clinic_id INTEGER DEFAULT NULL,
                role TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                pending_full_name TEXT DEFAULT NULL,

                FOREIGN KEY(clinic_id) REFERENCES clinics(id) ON DELETE CASCADE)
        """)

        cursor = await self.connection.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "pending_full_name" not in columns:
            await self.connection.execute(
                "ALTER TABLE users ADD COLUMN pending_full_name TEXT DEFAULT NULL"
            )

        await self._rebuild_users_if_column_order_stale()

        await self.connection.commit()

    async def _rebuild_users_if_column_order_stale(self) -> None:
        # gender/birth_date must sit right after full_name (confirmed layout),
        # which SQLite's ADD COLUMN cannot express — it only appends columns
        # at the end. A full table rebuild is the only way to reorder them.
        # This guard makes the rebuild idempotent by checking presence rather
        # than an exact column list: gender/birth_date only ever appear via a
        # fresh CREATE TABLE or this rebuild's own CREATE TABLE, both already
        # placing them right after full_name. Presence alone is therefore
        # sufficient proof that the rebuild already ran, so init() stays a
        # no-op on every later start — including after reminder_24h/reminder_2h
        # are dropped from users by UserSettingsRepository, which a stale
        # exact-list comparison would otherwise try to re-select and crash on.
        cursor = await self.connection.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "gender" in columns and "birth_date" in columns:
            return

        # reminder_24h/reminder_2h were dropped from the CREATE TABLE / ALTER
        # TABLE path above once reminder settings moved to UserSettingsRepository,
        # but this rebuild still targets a users_new schema that carries them
        # (so a mid-migration DB that has old reminder columns but not yet
        # gender/birth_date keeps them, ready for UserSettingsRepository's own
        # backfill+drop step). A genuinely legacy users table that predates the
        # reminder columns entirely (never had them) won't have them to select,
        # so fall back to the same literal default (1/true) the column
        # definitions themselves use.
        reminder_24h_select = "reminder_24h" if "reminder_24h" in columns else "1 AS reminder_24h"
        reminder_2h_select = "reminder_2h" if "reminder_2h" in columns else "1 AS reminder_2h"

        await self.connection.commit()
        await self.connection.execute("PRAGMA foreign_keys = OFF")

        try:
            await self.connection.execute("BEGIN")

            await self.connection.execute("""
                CREATE TABLE users_new(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER UNIQUE,
                    full_name TEXT NOT NULL,
                    gender TEXT DEFAULT NULL,
                    birth_date TEXT DEFAULT NULL,
                    phone TEXT UNIQUE NOT NULL,
                    clinic_id INTEGER DEFAULT NULL,
                    role TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reminder_24h INTEGER DEFAULT 1,
                    reminder_2h INTEGER DEFAULT 1,
                    pending_full_name TEXT DEFAULT NULL,

                    FOREIGN KEY(clinic_id) REFERENCES clinics(id) ON DELETE CASCADE)
            """)

            await self.connection.execute(f"""
                INSERT INTO users_new (
                    id, telegram_user_id, full_name, phone, clinic_id,
                    role, created_at, reminder_24h, reminder_2h, pending_full_name
                )
                SELECT
                    id, telegram_user_id, full_name, phone, clinic_id,
                    role, created_at, {reminder_24h_select}, {reminder_2h_select}, pending_full_name
                FROM users
            """)

            await self.connection.execute("DROP TABLE users")
            await self.connection.execute("ALTER TABLE users_new RENAME TO users")

            fk_cursor = await self.connection.execute("PRAGMA foreign_key_check")
            violations = await fk_cursor.fetchall()
            if violations:
                raise RuntimeError(f"users rebuild produced FK violations: {violations}")

            await self.connection.commit()
        except Exception:
            await self.connection.execute("ROLLBACK")
            raise
        finally:
            await self.connection.execute("PRAGMA foreign_keys = ON")

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
            cursor = await self.connection.execute(
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
            user.ID = cursor.lastrowid

        except aiosqlite.IntegrityError as error:
            if self._is_phone_unique_violation(error):
                raise PhoneAlreadyExistsError(PHONE_ALREADY_EXISTS_MESSAGE) from error
            raise UserAlreadyExistsError() from error

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

    async def get_clients_by_name_in_clinic(self, full_name: str, clinic_id: int) -> list[User]:
        parts = full_name.strip().title().split()
        if not parts:
            return []

        conditions = " OR ".join(["full_name LIKE ?"] * len(parts))
        params = [f"%{part}%" for part in parts]

        sql = USER_SELECT + f"""
        WHERE u.role = 'client'
        AND ({conditions})
        AND u.id IN (SELECT client_id FROM client_clinics WHERE clinic_id = ?)
        ORDER BY u.full_name, u.id
        """
        params.append(clinic_id)

        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()

        return [self._row_to_user(row) for row in rows]

    async def get_clients_by_exact_name(self, full_name: str, clinic_id: int) -> list[User]:
        cursor = await self.connection.execute(
            USER_SELECT + """
            WHERE u.role = 'client'
            AND u.full_name = ?
            AND u.id IN (SELECT client_id FROM client_clinics WHERE clinic_id = ?)
            ORDER BY u.full_name, u.id
            """,
            (full_name, clinic_id)
        )
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

    async def get_client_by_phone_in_clinic(self, phone: str, clinic_id: int) -> User | None:
        cursor = await self.connection.execute(
            USER_SELECT + """
            WHERE u.role = 'client'
            AND u.phone = ?
            AND u.id IN (SELECT client_id FROM client_clinics WHERE clinic_id = ?)
            """,
            (phone, clinic_id)
        )
        return self._row_to_user(await cursor.fetchone())

    async def update_client(self, user_id: int, user: User) -> User | None:
        try:
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
        except aiosqlite.IntegrityError as error:
            if self._is_phone_unique_violation(error):
                raise PhoneAlreadyExistsError(PHONE_ALREADY_EXISTS_MESSAGE) from error
            raise ValidationError("Не удалось обновить данные клиента.") from error

        return await self.get_client_by_id(user_id)

    @staticmethod
    def _is_phone_unique_violation(error: aiosqlite.IntegrityError) -> bool:
        message = str(error)
        return "UNIQUE constraint failed" in message and "phone" in message

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
        try:
            await self.connection.execute(
                """
                UPDATE users
                SET telegram_user_id = ?
                WHERE id = ?
                """,
                (telegram_user_id, user_id),
            )
            await self.connection.commit()
        except aiosqlite.IntegrityError as error:
            if self._is_telegram_id_unique_violation(error):
                raise UserAlreadyExistsError() from error
            raise ValidationError("Не удалось обновить данные клиента.") from error

    @staticmethod
    def _is_telegram_id_unique_violation(error: aiosqlite.IntegrityError) -> bool:
        message = str(error)
        return "UNIQUE constraint failed" in message and "telegram_user_id" in message

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
            gender=row[3],
            birth_date=row[4],
            phone=row[5],
            clinic_id=row[6],
            clinic_name=row[7],
            role=Role(row[8]) if row[8] else None,
            reminder_24h=bool(row[9]),
            reminder_2h=bool(row[10]),
            pending_full_name=row[11],
            created_at=row[12],
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

    async def get_clients_page_in_clinic(
        self, clinic_id: int, page: int, per_page: int = 10
    ) -> list[User]:
        """Получить страницу клиентов клиники"""
        offset = (page - 1) * per_page
        cursor = await self.connection.execute(
            USER_SELECT + """
            WHERE u.role = 'client'
            AND u.id IN (SELECT client_id FROM client_clinics WHERE clinic_id = ?)
            ORDER BY u.full_name, u.id
            LIMIT ? OFFSET ?
            """,
            (clinic_id, per_page, offset)
        )
        rows = await cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

    async def count_clients_in_clinic(self, clinic_id: int) -> int:
        """Получить общее количество клиентов клиники"""
        cursor = await self.connection.execute(
            """
            SELECT COUNT(*) FROM users
            WHERE role = 'client'
            AND id IN (SELECT client_id FROM client_clinics WHERE clinic_id = ?)
            """,
            (clinic_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_clients_missing_personal_data(self) -> list[User]:
        """Клиенты без даты рождения или пола, доступные для рассылки"""
        cursor = await self.connection.execute(
            USER_SELECT + """
            WHERE u.role = 'client'
            AND u.telegram_user_id IS NOT NULL
            AND (u.birth_date IS NULL OR u.gender IS NULL)
            ORDER BY u.full_name, u.id
            """
        )
        rows = await cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

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

    async def get_clients_by_name_page_in_clinic(
        self, full_name: str, clinic_id: int, page: int, per_page: int = 10
    ) -> list[User]:
        """Получить страницу результатов поиска по имени в пределах клиники"""
        parts = full_name.strip().title().split()
        if not parts:
            return []

        conditions = " OR ".join(["full_name LIKE ?"] * len(parts))
        params = [f"%{part}%" for part in parts]

        offset = (page - 1) * per_page

        sql = USER_SELECT + f"""
        WHERE u.role = 'client'
        AND ({conditions})
        AND u.id IN (SELECT client_id FROM client_clinics WHERE clinic_id = ?)
        ORDER BY u.full_name, u.id
        LIMIT ? OFFSET ?
        """
        params.append(clinic_id)
        params.extend([per_page, offset])

        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

    async def count_clients_by_name_in_clinic(self, full_name: str, clinic_id: int) -> int:
        """Получить количество результатов поиска по имени в пределах клиники"""
        parts = full_name.strip().title().split()
        if not parts:
            return 0

        conditions = " OR ".join(["full_name LIKE ?"] * len(parts))
        params = [f"%{part}%" for part in parts]

        sql = f"""SELECT COUNT(*) FROM users WHERE role = 'client' AND ({conditions})
        AND id IN (SELECT client_id FROM client_clinics WHERE clinic_id = ?)"""
        params.append(clinic_id)
        cursor = await self.connection.execute(sql, params)
        row = await cursor.fetchone()
        return row[0] if row else 0