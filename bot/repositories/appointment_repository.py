import aiosqlite

from bot.models.appointment import Appointment
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy

APPOINTMENT_SELECT = """
SELECT
    a.id,
    a.clinic_id,
    a.client_id,
    a.admin_id,
    a.datetime,
    a.purpose,
    a.created_by,
    a.status,
    a.created_at,
    c.name AS clinic_name,
    a.admin_tg_id,
    u.full_name AS client_full_name,
    u.phone AS client_phone,
    a.notification_message_id,
    a.proposed_datetime,
    a.proposal_message_id,
    a.proposed_by
FROM appointments a
LEFT JOIN clinics c ON c.id = a.clinic_id
LEFT JOIN users u ON u.id = a.client_id
"""


class AppointmentRepository:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection

    async def init(self) -> None:
        # Rename columns if they exist (migration from old schema)
        try:
            await self.connection.execute(
                "ALTER TABLE appointments RENAME COLUMN doctor_id TO admin_id"
            )
        except Exception:
            pass
        try:
            await self.connection.execute(
                "ALTER TABLE appointments RENAME COLUMN created_by_telegram_id TO admin_tg_id"
            )
        except Exception:
            pass

        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS appointments(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clinic_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                admin_id INTEGER DEFAULT NULL,
                datetime TIMESTAMP NOT NULL,
                purpose TEXT,
                created_by TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                admin_tg_id INTEGER DEFAULT NULL,
                notification_message_id INTEGER DEFAULT NULL,
                proposed_datetime TIMESTAMP DEFAULT NULL,
                proposal_message_id INTEGER DEFAULT NULL,
                proposed_by TEXT DEFAULT NULL,

                FOREIGN KEY(clinic_id) REFERENCES clinics(id) ON DELETE CASCADE,
                FOREIGN KEY(client_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(admin_id) REFERENCES users(id) ON DELETE SET NULL
            )
        """)

        # Ensure admin_tg_id column exists for existing databases
        # (covers very old databases that predate this column entirely)
        cursor = await self.connection.execute(
            "PRAGMA table_info(appointments)"
        )
        columns = {row[1] for row in await cursor.fetchall()}
        if "admin_tg_id" not in columns:
            await self.connection.execute(
                "ALTER TABLE appointments ADD COLUMN admin_tg_id INTEGER DEFAULT NULL"
            )

        # Ensure notification_message_id column exists for existing databases
        if "notification_message_id" not in columns:
            await self.connection.execute(
                "ALTER TABLE appointments ADD COLUMN notification_message_id INTEGER DEFAULT NULL"
            )

        # Ensure proposed_datetime column exists for existing databases
        if "proposed_datetime" not in columns:
            await self.connection.execute(
                "ALTER TABLE appointments ADD COLUMN proposed_datetime TIMESTAMP DEFAULT NULL"
            )

        # Ensure proposal_message_id column exists for existing databases
        if "proposal_message_id" not in columns:
            await self.connection.execute(
                "ALTER TABLE appointments ADD COLUMN proposal_message_id INTEGER DEFAULT NULL"
            )

        # Ensure proposed_by column exists for existing databases
        if "proposed_by" not in columns:
            await self.connection.execute(
                "ALTER TABLE appointments ADD COLUMN proposed_by TEXT DEFAULT NULL"
            )

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
            APPOINTMENT_SELECT + "\nWHERE a.id = ?",
            (appointment_id,),
        )
        return self._row_to_appointment(await cursor.fetchone())

    async def get_appointments_by_client_id(self, client_id: int) -> list[Appointment]:
        cursor = await self.connection.execute(
            APPOINTMENT_SELECT + "\nWHERE a.client_id = ?\nORDER BY a.created_at DESC",
            (client_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def get_appointments_by_telegram_id(self, telegram_user_id: int) -> list[Appointment]:
        cursor = await self.connection.execute(
            """
            SELECT
                a.id, a.clinic_id, a.client_id, a.admin_id,
                a.datetime, a.purpose, a.created_by, a.status, a.created_at,
                c.name AS clinic_name, a.admin_tg_id,
                u.full_name AS client_full_name, u.phone AS client_phone,
                a.notification_message_id, a.proposed_datetime, a.proposal_message_id,
                a.proposed_by
            FROM appointments a
            JOIN users u ON u.id = a.client_id
            LEFT JOIN clinics c ON c.id = a.clinic_id
            WHERE u.telegram_user_id = ?
            ORDER BY a.created_at DESC
            """,
            (telegram_user_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def create_appointment(self, appointment: Appointment) -> Appointment:
        cursor = await self.connection.execute(
            """
            INSERT INTO appointments(
                clinic_id, client_id, admin_id,
                datetime, purpose, created_by, status, admin_tg_id, created_at,
                notification_message_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                appointment.clinic_id,
                appointment.client_id,
                appointment.doctor_id,
                appointment.datetime,
                appointment.purpose,
                appointment.created_by.value,
                appointment.status.value,
                appointment.created_by_telegram_id,
                appointment.created_at,
                appointment.notification_message_id,
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
                admin_id = ?,
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

    async def update_notification_message_id(self, appointment_id: int, message_id: int) -> None:
        await self.connection.execute(
            "UPDATE appointments SET notification_message_id = ? WHERE id = ?",
            (message_id, appointment_id),
        )
        await self.connection.commit()

    async def update_proposed_datetime(self, appointment_id: int, proposed_datetime: str | None) -> None:
        await self.connection.execute(
            "UPDATE appointments SET proposed_datetime = ? WHERE id = ?",
            (proposed_datetime, appointment_id),
        )
        await self.connection.commit()

    async def update_proposal_message_id(self, appointment_id: int, message_id: int | None) -> None:
        await self.connection.execute(
            "UPDATE appointments SET proposal_message_id = ? WHERE id = ?",
            (message_id, appointment_id),
        )
        await self.connection.commit()

    async def update_proposed_by(self, appointment_id: int, proposed_by: CreatedBy | None) -> None:
        await self.connection.execute(
            "UPDATE appointments SET proposed_by = ? WHERE id = ?",
            (proposed_by.value if proposed_by else None, appointment_id),
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

    async def get_all_appointments(self) -> list[Appointment]:
        cursor = await self.connection.execute(
            APPOINTMENT_SELECT + "\nORDER BY a.created_at DESC"
        )
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def count_appointments(self) -> int:
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM appointments"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_appointments_by_client_ids(self, client_ids: list[int]) -> list[Appointment]:
        if not client_ids:
            return []
        placeholders = ",".join("?" * len(client_ids))
        cursor = await self.connection.execute(
            APPOINTMENT_SELECT + f"\nWHERE a.client_id IN ({placeholders})\nORDER BY a.created_at DESC",
            client_ids,
        )
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def get_appointments_page(self, page: int, per_page: int = 10) -> list[Appointment]:
        """Получить страницу всех записей"""
        offset = (page - 1) * per_page
        cursor = await self.connection.execute(
            APPOINTMENT_SELECT + """
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT ? OFFSET ?
            """,
            (per_page, offset),
        )
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def get_appointments_by_name_page(
        self, full_name: str, page: int, per_page: int = 10
    ) -> list[Appointment]:
        """Получить страницу результатов поиска записей по имени клиента"""
        parts = full_name.strip().title().split()
        if not parts:
            return []

        conditions = " OR ".join(["u.full_name LIKE ?"] * len(parts))
        params = [f"%{part}%" for part in parts]

        offset = (page - 1) * per_page

        sql = APPOINTMENT_SELECT + f"""
        WHERE ({conditions})
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT ? OFFSET ?
        """
        params.extend([per_page, offset])

        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def count_appointments_by_name(self, full_name: str) -> int:
        """Получить количество результатов поиска записей по имени клиента"""
        parts = full_name.strip().title().split()
        if not parts:
            return 0

        conditions = " OR ".join(["u.full_name LIKE ?"] * len(parts))
        params = [f"%{part}%" for part in parts]

        sql = f"""
        SELECT COUNT(*)
        FROM appointments a
        LEFT JOIN users u ON u.id = a.client_id
        WHERE ({conditions})
        """
        cursor = await self.connection.execute(sql, params)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_appointments_by_client_id_page(
        self, client_id: int, page: int, per_page: int = 10
    ) -> list[Appointment]:
        """Получить страницу записей конкретного клиента"""
        offset = (page - 1) * per_page
        cursor = await self.connection.execute(
            APPOINTMENT_SELECT + """
            WHERE a.client_id = ?
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT ? OFFSET ?
            """,
            (client_id, per_page, offset),
        )
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def count_appointments_by_client_id(self, client_id: int) -> int:
        """Получить количество записей конкретного клиента"""
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM appointments WHERE client_id = ?",
            (client_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

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
            created_by_telegram_id=row[10],
            client_full_name=row[11],
            client_phone=row[12],
            notification_message_id=row[13],
            proposed_datetime=row[14],
            proposal_message_id=row[15],
            proposed_by=CreatedBy(row[16]) if row[16] else None,
        )
