import aiosqlite

from bot.exceptions.user_exceptions import UserAlreadyExistsError, UserNotFoundError
from bot.models.clinic import Clinic


class ClinicRepository:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection


    async def init(self) -> None:
        await self.connection.execute(
            """"
            CREATE TABLE IF NOT EXISTS clinics(name TEXT DEFAULT NULL, 
            clinic_id INTEGER PRIMARY KEY AUTOINCREMENT)
            
            INSERT INTO clinics(name) VALUES ('Зуб Мудрости')
            """
        )
        await self.connection.commit()


    async def get_clinic_by_id(self, clinic_id: int) -> Clinic | None:

        cursor = await self.connection.execute(
            """
            SELECT * FROM clinics WHERE clinic_id = ?"""
            , (clinic_id,)
        )
        return self._row_to_clinic(await cursor.fetchone())

    async def get_clients_by_name(self, name: str) -> list[Clinic] | None:
        parts = name.strip().title().split()

        conditions = " OR ".join(["name LIKE ?"] * len(parts))
        params = [f"%{part}%" for part in parts]

        sql = f"""
        SELECT *
        FROM clinics
        WHERE ({conditions})
        ORDER BY name
        """

        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()

        return [self._row_to_clinic(row) for row in rows]

    def _row_to_clinic(self, row) -> Clinic | None:
        if row is None:
            return None

        return Clinic(
            clinic_id=row[0],
            name=row[1],
        )


