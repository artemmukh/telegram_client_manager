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

        await self.connection.execute(
            """
            SELECT * FROM clinics WHERE clinic_id = ?"""
            , (clinic_id,)
        )
        await self.connection.commit()


