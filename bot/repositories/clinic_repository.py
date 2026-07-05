import aiosqlite

from bot.models.clinic import Clinic


class ClinicRepository:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection


    async def init(self) -> None:
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS clinics(
            
            id INTEGER UNIQUE PRIMARY KEY AUTOINCREMENT,
            name TEXT DEFAULT NULL,
            token TEXT UNIQUE NOT NULL)
            """
        )

        await self.connection.execute("""
                
            INSERT OR IGNORE INTO clinics (name, token)
            VALUES (
                'Зуб Мудрости',
                'x7A92JdPkLmQe81'
);

        """)

        await self.connection.commit()


    async def get_clinic_by_id(self, clinic_id: int) -> Clinic | None:

        cursor = await self.connection.execute(
            """
            SELECT id, name, token FROM clinics WHERE id = ?"""
            , (clinic_id,)
        )
        return self._row_to_clinic(await cursor.fetchone())

    async def get_clients_by_name(self, name: str) -> list[Clinic] | None:
        parts = name.strip().title().split()

        conditions = " OR ".join(["name LIKE ?"] * len(parts))
        params = [f"%{part}%" for part in parts]

        sql = f"""
        SELECT id, name, token
        FROM clinics
        WHERE ({conditions})
        ORDER BY name
        """

        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()

        return [self._row_to_clinic(row) for row in rows]

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


