import aiosqlite

from bot.models.appointment import Appointment
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy

APPOINTMENT_SELECT = """
SELECT
    a.id,
    a.clinic_id,
    a.client_id,
    a.doctor_id,
    a.datetime,
    a.purpose,
    a.created_by,
    a.status,
    a.created_at,
    c.name AS clinic_name
FROM appointments a
LEFT JOIN clinics c ON c.id = a.clinic_id
"""


class AppointmentRepository:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection

    async def init(self) -> None:
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS appointments(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clinic_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                doctor_id INTEGER DEFAULT NULL,
                datetime TIMESTAMP NOT NULL,
                purpose TEXT,
                created_by TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(clinic_id) REFERENCES clinics(id) ON DELETE CASCADE,
                FOREIGN KEY(client_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(doctor_id) REFERENCES users(id) ON DELETE SET NULL
            )
        """)
        await self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_appointments_clinic_datetime
            ON appointments(clinic_id, datetime)
        """)
        await self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_appointments_client
            ON appointments(client_id)
        """)
        await self.connection.commit()

    async def get_appointment_by_id(self, appointment_id: int) -> Appointment | None:
        cursor = await self.connection.execute(
            APPOINTMENT_SELECT + "WHERE a.id = ?",
            (appointment_id,),
        )
        return self._row_to_appointment(await cursor.fetchone())

    async def get_appointments_by_client_id(self, client_id: int) -> list[Appointment]:
        cursor = await self.connection.execute(
            APPOINTMENT_SELECT + "WHERE a.client_id = ? ORDER BY a.datetime",
            (client_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def get_appointments_by_telegram_id(self, telegram_user_id: int) -> list[Appointment]:
        cursor = await self.connection.execute(
            """
            SELECT
                a.id, a.clinic_id, a.client_id, a.doctor_id,
                a.datetime, a.purpose, a.created_by, a.status, a.created_at,
                c.name AS clinic_name
            FROM appointments a
            JOIN users u ON u.id = a.client_id
            LEFT JOIN clinics c ON c.id = a.clinic_id
            WHERE u.telegram_user_id = ?
            ORDER BY a.datetime
            """,
            (telegram_user_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def create_appointment(self, appointment: Appointment) -> Appointment:
        cursor = await self.connection.execute(
            """
            INSERT INTO appointments(
                clinic_id, client_id, doctor_id,
                datetime, purpose, created_by, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                appointment.clinic_id,
                appointment.client_id,
                appointment.doctor_id,
                appointment.datetime,
                appointment.purpose,
                appointment.created_by.value,
                appointment.status.value,
            ),
        )
        await self.connection.commit()

        appointment_id = cursor.lastrowid
        created_appointment = await self.get_appointment_by_id(appointment_id)
        return created_appointment

    async def update_appointment(self, appointment_id: int, appointment: Appointment) -> None:
        await self.connection.execute(
            """
            UPDATE appointments
            SET
                doctor_id = ?,
                datetime = ?,
                purpose = ?,
                status = ?
            WHERE id = ?
            """,
            (
                appointment.doctor_id,
                appointment.datetime,
                appointment.purpose,
                appointment.status.value,
                appointment_id,
            ),
        )
        await self.connection.commit()

    async def update_appointment_status(self, appointment_id: int, status: AppointmentStatus) -> None:
        await self.connection.execute(
            "UPDATE appointments SET status = ? WHERE id = ?",
            (status.value, appointment_id),
        )
        await self.connection.commit()

    async def delete_appointment(self, appointment_id: int) -> None:
        await self.connection.execute(
            "DELETE FROM appointments WHERE id = ?",
            (appointment_id,),
        )
        await self.connection.commit()

    async def appointment_exists(self, appointment_id: int) -> bool:
        cursor = await self.connection.execute(
            "SELECT 1 FROM appointments WHERE id = ?",
            (appointment_id,),
        )
        return await cursor.fetchone() is not None

    def _row_to_appointment(self, row) -> Appointment | None:
        if row is None:
            return None
        return Appointment(
            id=row[0],
            clinic_id=row[1],
            client_id=row[2],
            doctor_id=row[3],
            datetime=row[4],
            purpose=row[5],
            created_by=CreatedBy(row[6]),
            status=AppointmentStatus(row[7]),
            created_at=row[8],
            clinic_name=row[9],
        )
