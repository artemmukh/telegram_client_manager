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
    a.status_updated_at,
    c.name AS clinic_name,
    a.admin_tg_id,
    u.full_name AS client_full_name,
    u.phone AS client_phone,
    a.notification_message_id,
    a.proposed_datetime,
    a.proposal_message_id,
    a.proposed_by,
    a.admin_notification_message_id,
    d.full_name AS doctor_full_name,
    d.phone AS doctor_phone,
    a.price
FROM appointments a
LEFT JOIN clinics c ON c.id = a.clinic_id
LEFT JOIN users u ON u.id = a.client_id
LEFT JOIN users d ON d.id = a.admin_id
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
                status_updated_at TIMESTAMP DEFAULT NULL,
                admin_tg_id INTEGER DEFAULT NULL,
                notification_message_id INTEGER DEFAULT NULL,
                proposed_datetime TIMESTAMP DEFAULT NULL,
                proposal_message_id INTEGER DEFAULT NULL,
                proposed_by TEXT DEFAULT NULL,
                admin_notification_message_id INTEGER DEFAULT NULL,
                price REAL DEFAULT NULL,

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

        # Ensure admin_notification_message_id column exists for existing databases
        if "admin_notification_message_id" not in columns:
            await self.connection.execute(
                "ALTER TABLE appointments ADD COLUMN admin_notification_message_id INTEGER DEFAULT NULL"
            )

        # Ensure status_updated_at column exists for existing databases
        if "status_updated_at" not in columns:
            await self.connection.execute(
                "ALTER TABLE appointments ADD COLUMN status_updated_at TIMESTAMP DEFAULT NULL"
            )
            await self.connection.execute(
                "UPDATE appointments SET status_updated_at = created_at WHERE status_updated_at IS NULL"
            )

        # Ensure price column exists for existing databases
        if "price" not in columns:
            await self.connection.execute(
                "ALTER TABLE appointments ADD COLUMN price REAL DEFAULT NULL"
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

    async def get_appointments_by_client_id(
        self, client_id: int, clinic_id: int, doctor_id: int | None = None
    ) -> list[Appointment]:
        conditions = ["a.client_id = ?", "a.clinic_id = ?"]
        params = [client_id, clinic_id]

        if doctor_id is not None:
            conditions.append("a.admin_id = ?")
            params.append(doctor_id)

        sql = APPOINTMENT_SELECT + f"\nWHERE {' AND '.join(conditions)}\nORDER BY a.created_at DESC"
        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def get_appointments_by_doctor_and_date(self, doctor_id: int, date: str) -> list[Appointment]:
        cursor = await self.connection.execute(
            APPOINTMENT_SELECT + "\nWHERE a.admin_id = ? AND a.datetime LIKE ? AND a.status = ?",
            (doctor_id, f"{date}%", AppointmentStatus.CONFIRMED.value),
        )
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def get_appointments_by_telegram_id(self, telegram_user_id: int) -> list[Appointment]:
        cursor = await self.connection.execute(
            """
            SELECT
                a.id, a.clinic_id, a.client_id, a.admin_id,
                a.datetime, a.purpose, a.created_by, a.status, a.created_at,
                a.status_updated_at,
                c.name AS clinic_name, a.admin_tg_id,
                u.full_name AS client_full_name, u.phone AS client_phone,
                a.notification_message_id, a.proposed_datetime, a.proposal_message_id,
                a.proposed_by, a.admin_notification_message_id,
                d.full_name AS doctor_full_name, d.phone AS doctor_phone,
                a.price
            FROM appointments a
            JOIN users u ON u.id = a.client_id
            LEFT JOIN clinics c ON c.id = a.clinic_id
            LEFT JOIN users d ON d.id = a.admin_id
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
                status_updated_at, notification_message_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    async def update_appointment_status(
        self, appointment_id: int, status: AppointmentStatus, status_updated_at: str
    ) -> None:
        await self.connection.execute(
            "UPDATE appointments SET status = ?, status_updated_at = ? WHERE id = ?",
            (status.value, status_updated_at, appointment_id),
        )
        await self.connection.commit()

    async def update_notification_message_id(self, appointment_id: int, message_id: int) -> None:
        await self.connection.execute(
            "UPDATE appointments SET notification_message_id = ? WHERE id = ?",
            (message_id, appointment_id),
        )
        await self.connection.commit()

    async def update_appointment_price(self, appointment_id: int, price: float | None) -> None:
        await self.connection.execute(
            "UPDATE appointments SET price = ? WHERE id = ?",
            (price, appointment_id),
        )
        await self.connection.commit()

    async def update_admin_notification_message_id(self, appointment_id: int, message_id: int) -> None:
        await self.connection.execute(
            "UPDATE appointments SET admin_notification_message_id = ? WHERE id = ?",
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

    async def count_appointments(self, clinic_id: int, doctor_id: int | None = None) -> int:
        conditions = ["clinic_id = ?"]
        params = [clinic_id]

        if doctor_id is not None:
            conditions.append("admin_id = ?")
            params.append(doctor_id)

        sql = f"SELECT COUNT(*) FROM appointments WHERE {' AND '.join(conditions)}"
        cursor = await self.connection.execute(sql, params)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_appointments_by_client_ids(
        self, client_ids: list[int], clinic_id: int, doctor_id: int | None = None
    ) -> list[Appointment]:
        if not client_ids:
            return []
        placeholders = ",".join("?" * len(client_ids))
        conditions = [f"a.client_id IN ({placeholders})", "a.clinic_id = ?"]
        params = [*client_ids, clinic_id]

        if doctor_id is not None:
            conditions.append("a.admin_id = ?")
            params.append(doctor_id)

        sql = APPOINTMENT_SELECT + f"\nWHERE {' AND '.join(conditions)}\nORDER BY a.created_at DESC"
        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def get_appointments_page(
        self, page: int, clinic_id: int, doctor_id: int | None = None, per_page: int = 10
    ) -> list[Appointment]:
        """Получить страницу всех записей"""
        offset = (page - 1) * per_page
        conditions = ["a.clinic_id = ?"]
        params = [clinic_id]

        if doctor_id is not None:
            conditions.append("a.admin_id = ?")
            params.append(doctor_id)

        sql = APPOINTMENT_SELECT + f"""
        WHERE {' AND '.join(conditions)}
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT ? OFFSET ?
        """
        params.extend([per_page, offset])

        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def get_appointments_by_name(
        self, full_name: str, clinic_id: int, doctor_id: int | None = None
    ) -> list[Appointment]:
        """Получить все записи, соответствующие поиску по имени клиента"""
        parts = full_name.strip().title().split()
        if not parts:
            return []

        name_conditions = " OR ".join(["u.full_name LIKE ?"] * len(parts))
        params = [f"%{part}%" for part in parts]

        conditions = [f"({name_conditions})", "a.clinic_id = ?"]
        params.append(clinic_id)

        if doctor_id is not None:
            conditions.append("a.admin_id = ?")
            params.append(doctor_id)

        sql = APPOINTMENT_SELECT + f"""
        WHERE {' AND '.join(conditions)}
        ORDER BY a.created_at DESC
        """

        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def get_appointments_by_name_page(
        self, full_name: str, page: int, clinic_id: int, doctor_id: int | None = None, per_page: int = 10
    ) -> list[Appointment]:
        """Получить страницу результатов поиска записей по имени клиента"""
        parts = full_name.strip().title().split()
        if not parts:
            return []

        name_conditions = " OR ".join(["u.full_name LIKE ?"] * len(parts))
        params = [f"%{part}%" for part in parts]

        conditions = [f"({name_conditions})", "a.clinic_id = ?"]
        params.append(clinic_id)

        if doctor_id is not None:
            conditions.append("a.admin_id = ?")
            params.append(doctor_id)

        offset = (page - 1) * per_page

        sql = APPOINTMENT_SELECT + f"""
        WHERE {' AND '.join(conditions)}
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT ? OFFSET ?
        """
        params.extend([per_page, offset])

        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def count_appointments_by_name(
        self, full_name: str, clinic_id: int, doctor_id: int | None = None
    ) -> int:
        """Получить количество результатов поиска записей по имени клиента"""
        parts = full_name.strip().title().split()
        if not parts:
            return 0

        name_conditions = " OR ".join(["u.full_name LIKE ?"] * len(parts))
        params = [f"%{part}%" for part in parts]

        conditions = [f"({name_conditions})", "a.clinic_id = ?"]
        params.append(clinic_id)

        if doctor_id is not None:
            conditions.append("a.admin_id = ?")
            params.append(doctor_id)

        sql = f"""
        SELECT COUNT(*)
        FROM appointments a
        LEFT JOIN users u ON u.id = a.client_id
        WHERE {' AND '.join(conditions)}
        """
        cursor = await self.connection.execute(sql, params)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_appointments_by_status_page(
        self,
        status: AppointmentStatus,
        page: int,
        clinic_id: int,
        doctor_id: int | None = None,
        per_page: int = 10,
    ) -> list[Appointment]:
        """Получить страницу записей с определённым статусом (для вкладок админского списка)"""
        offset = (page - 1) * per_page
        order_by = self._status_order_by(status)

        conditions = ["a.status = ?", "a.clinic_id = ?"]
        params = [status.value, clinic_id]

        if doctor_id is not None:
            conditions.append("a.admin_id = ?")
            params.append(doctor_id)

        sql = APPOINTMENT_SELECT + f"""
        WHERE {' AND '.join(conditions)}
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
        """
        params.extend([per_page, offset])

        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def count_appointments_by_status(
        self, status: AppointmentStatus, clinic_id: int, doctor_id: int | None = None
    ) -> int:
        """Получить количество записей с определённым статусом"""
        conditions = ["status = ?", "clinic_id = ?"]
        params = [status.value, clinic_id]

        if doctor_id is not None:
            conditions.append("admin_id = ?")
            params.append(doctor_id)

        sql = f"SELECT COUNT(*) FROM appointments WHERE {' AND '.join(conditions)}"
        cursor = await self.connection.execute(sql, params)
        row = await cursor.fetchone()
        return row[0] if row else 0

    @staticmethod
    def _status_order_by(status: AppointmentStatus) -> str:
        if status == AppointmentStatus.CONFIRMED:
            return "a.datetime ASC, a.id ASC"
        if status == AppointmentStatus.PENDING:
            return "a.created_at DESC, a.id DESC"
        return "COALESCE(a.status_updated_at, a.created_at) DESC, a.id DESC"

    async def get_appointments_by_client_id_page(
        self, client_id: int, page: int, clinic_id: int, doctor_id: int | None = None, per_page: int = 10
    ) -> list[Appointment]:
        """Получить страницу записей конкретного клиента"""
        offset = (page - 1) * per_page

        conditions = ["a.client_id = ?", "a.clinic_id = ?"]
        params = [client_id, clinic_id]

        if doctor_id is not None:
            conditions.append("a.admin_id = ?")
            params.append(doctor_id)

        sql = APPOINTMENT_SELECT + f"""
        WHERE {' AND '.join(conditions)}
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT ? OFFSET ?
        """
        params.extend([per_page, offset])

        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def count_appointments_by_client_id(
        self, client_id: int, clinic_id: int, doctor_id: int | None = None
    ) -> int:
        """Получить количество записей конкретного клиента"""
        conditions = ["client_id = ?", "clinic_id = ?"]
        params = [client_id, clinic_id]

        if doctor_id is not None:
            conditions.append("admin_id = ?")
            params.append(doctor_id)

        sql = f"SELECT COUNT(*) FROM appointments WHERE {' AND '.join(conditions)}"
        cursor = await self.connection.execute(sql, params)
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
            status_updated_at=row[9],
            clinic_name=row[10],
            created_by_telegram_id=row[11],
            client_full_name=row[12],
            client_phone=row[13],
            notification_message_id=row[14],
            proposed_datetime=row[15],
            proposal_message_id=row[16],
            proposed_by=CreatedBy(row[17]) if row[17] else None,
            admin_notification_message_id=row[18],
            doctor_full_name=row[19],
            doctor_phone=row[20],
            price=row[21],
        )
