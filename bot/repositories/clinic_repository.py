import aiosqlite

from bot.config.clinic_instances import CLINIC_SEED_BY_INSTANCE
from bot.models.clinic import Clinic


class ClinicRepository:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection


    async def init(self, instance: str) -> None:
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS clinics(

            id INTEGER UNIQUE PRIMARY KEY AUTOINCREMENT,
            name TEXT DEFAULT NULL,
            token TEXT UNIQUE NOT NULL)
            """
        )

        # Each instance now runs its own dedicated database (one clinic per
        # DB), so only that instance's own clinic is seeded here -- not both.
        clinic = CLINIC_SEED_BY_INSTANCE[instance]
        await self.connection.execute(
            "INSERT OR IGNORE INTO clinics (name, token) VALUES (?, ?)",
            (clinic["name"], clinic["token"]),
        )

        await self.connection.commit()


    async def get_only_clinic(self) -> Clinic | None:
        # For the token-less /start fallback: a single-clinic database has
        # exactly one row here, so we can resolve it without a token. Returns
        # None (rather than guessing) if the database ever ends up with zero
        # or more than one clinic.
        cursor = await self.connection.execute(
            "SELECT id, name, token FROM clinics LIMIT 2"
        )
        rows = await cursor.fetchall()

        if len(rows) != 1:
            return None

        return self._row_to_clinic(rows[0])


    async def get_clinic_by_id(self, clinic_id: int) -> Clinic | None:

        cursor = await self.connection.execute(
            """
            SELECT id, name, token FROM clinics WHERE id = ?"""
            , (clinic_id,)
        )
        return self._row_to_clinic(await cursor.fetchone())

    async def get_clinic_by_token(self, token: str) -> Clinic | None:
        cursor = await self.connection.execute(
            """
            SELECT id, name, token
            FROM clinics
            WHERE token = ?
            """,
            (token,)
        )
        return self._row_to_clinic(await cursor.fetchone())

    def _row_to_clinic(self, row) -> Clinic | None:
        if row is None:
            return None

        return Clinic(
            clinic_id=row[0],
            name=row[1],
            token=row[2],
        )


