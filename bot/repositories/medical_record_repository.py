import logging

import aiosqlite

from bot.models.medical_record import MedicalRecord
from bot.utils.medical_record_enums import MedicalRecordStatus

logger = logging.getLogger(__name__)

MEDICAL_RECORD_SELECT = """
SELECT
    id,
    appointment_id,
    status,
    file_path,
    created_at,
    updated_at,
    error_message
FROM medical_records
"""


class MedicalRecordRepository:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection

    async def init(self) -> None:
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS medical_records(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                file_path TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT NULL,
                error_message TEXT DEFAULT NULL,

                FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
            )
        """)

        # Defensive migration guard, matching the PRAGMA table_info/ALTER TABLE
        # pattern used by the other repositories in this project (see
        # AppointmentRepository.init()) — currently a no-op since every column
        # above already ships in the CREATE TABLE, but kept here so a future
        # column addition follows the same additive-migration path instead of
        # a fresh ad-hoc pattern.
        cursor = await self.connection.execute("PRAGMA table_info(medical_records)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "error_message" not in columns:
            await self.connection.execute(
                "ALTER TABLE medical_records ADD COLUMN error_message TEXT DEFAULT NULL"
            )

        # No explicit index on appointment_id: the UNIQUE constraint above
        # already creates one (both SQLite and Postgres auto-index UNIQUE
        # columns), and the only lookup paths are appointment_id (covered
        # by that unique index) and id (covered by the primary key).

        await self.connection.commit()

    async def create_pending(self, appointment_id: int) -> MedicalRecord:
        try:
            cursor = await self.connection.execute(
                """
                INSERT INTO medical_records(appointment_id, status)
                VALUES (?, ?)
                """,
                (appointment_id, MedicalRecordStatus.PENDING.value),
            )
            await self.connection.commit()
        except aiosqlite.IntegrityError:
            # A row for this appointment_id already exists — this is a
            # deliberate race guard for concurrent trigger paths (e.g. a
            # completion job and a "get history" button press both trying
            # to create the pending row for the same appointment). Treat
            # "already exists" the same as "just created" so callers get a
            # uniform MedicalRecord back instead of a raw driver error.
            #
            # Roll back first: SQLite tolerates querying right after a failed
            # INSERT, but Postgres aborts the whole transaction on an
            # integrity error and refuses every subsequent statement until a
            # ROLLBACK — required for this fallback to keep working post-migration.
            await self.connection.rollback()
            existing = await self.get_by_appointment_id(appointment_id)
            if existing is not None:
                return existing
            raise

        record_id = cursor.lastrowid
        return await self._get_by_id(record_id)

    async def get_by_appointment_id(self, appointment_id: int) -> MedicalRecord | None:
        cursor = await self.connection.execute(
            MEDICAL_RECORD_SELECT + "\nWHERE appointment_id = ?",
            (appointment_id,),
        )
        return self._row_to_medical_record(await cursor.fetchone())

    async def mark_generating(self, id: int) -> None:
        await self.connection.execute(
            """
            UPDATE medical_records
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (MedicalRecordStatus.GENERATING.value, id),
        )
        await self.connection.commit()

    async def mark_pending(self, id: int) -> None:
        await self.connection.execute(
            """
            UPDATE medical_records
            SET status = ?, file_path = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (MedicalRecordStatus.PENDING.value, id),
        )
        await self.connection.commit()

    async def mark_ready(self, id: int, file_path: str, partial: bool) -> None:
        status = MedicalRecordStatus.READY_PARTIAL if partial else MedicalRecordStatus.READY
        await self.connection.execute(
            """
            UPDATE medical_records
            SET status = ?, file_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status.value, file_path, id),
        )
        await self.connection.commit()

    async def mark_failed(self, id: int, error_message: str) -> None:
        await self.connection.execute(
            """
            UPDATE medical_records
            SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (MedicalRecordStatus.FAILED.value, error_message, id),
        )
        await self.connection.commit()

    async def _get_by_id(self, id: int) -> MedicalRecord | None:
        cursor = await self.connection.execute(
            MEDICAL_RECORD_SELECT + "\nWHERE id = ?",
            (id,),
        )
        return self._row_to_medical_record(await cursor.fetchone())

    def _row_to_medical_record(self, row) -> MedicalRecord | None:
        if row is None:
            return None
        return MedicalRecord(
            id=row[0],
            appointment_id=row[1],
            status=MedicalRecordStatus(row[2]),
            file_path=row[3],
            created_at=row[4],
            updated_at=row[5],
            error_message=row[6],
        )
