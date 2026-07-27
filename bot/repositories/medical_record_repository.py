import logging

import aiosqlite

from bot.models.medical_record import MedicalRecord
from bot.utils.medical_record_enums import MedicalRecordStatus

logger = logging.getLogger(__name__)

MEDICAL_RECORD_SELECT = """
SELECT
    id,
    appointment_id,
    diagnosis,
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
                appointment_id INTEGER NOT NULL,
                diagnosis TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                file_path TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT NULL,
                error_message TEXT DEFAULT NULL,

                FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
                UNIQUE(appointment_id, diagnosis)
            )
        """)

        cursor = await self.connection.execute("PRAGMA table_info(medical_records)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "error_message" not in columns:
            await self.connection.execute(
                "ALTER TABLE medical_records ADD COLUMN error_message TEXT DEFAULT NULL"
            )

        if "diagnosis" not in columns:
            await self.connection.execute(
                "ALTER TABLE medical_records ADD COLUMN diagnosis TEXT NOT NULL DEFAULT ''"
            )

        await self._rebuild_if_legacy_unique_constraint()

        await self.connection.commit()

    async def _rebuild_if_legacy_unique_constraint(self) -> None:
        """One-time rebuild of medical_records for DBs created before the
        appointment_id/diagnosis composite key.

        SQLite cannot ALTER a UNIQUE constraint away, so this detects the old
        auto-index SQLite creates for a single-column `UNIQUE(appointment_id)`
        constraint (an index whose only column is appointment_id) and, if
        found, rebuilds the table with the new schema via the standard
        create-new/copy/drop/rename sequence. Diagnosis for pre-existing rows
        is backfilled from the linked appointment's purpose (empty string if
        the appointment no longer exists). No-op on a fresh or already
        migrated database, and safe to run again since the rebuilt table's
        composite unique index no longer matches the legacy shape.
        """
        cursor = await self.connection.execute("PRAGMA index_list(medical_records)")
        indexes = await cursor.fetchall()

        legacy_index_name = None
        for index in indexes:
            index_name, is_unique = index[1], index[2]
            if not is_unique:
                continue

            info_cursor = await self.connection.execute(f"PRAGMA index_info({index_name})")
            index_columns = [row[2] for row in await info_cursor.fetchall()]
            if index_columns == ["appointment_id"]:
                legacy_index_name = index_name
                break

        if legacy_index_name is None:
            return

        logger.info(
            "Rebuilding medical_records: replacing legacy UNIQUE(appointment_id) "
            "constraint (index %s) with UNIQUE(appointment_id, diagnosis)",
            legacy_index_name,
        )

        await self.connection.execute("DROP TABLE IF EXISTS medical_records_new")

        await self.connection.execute("BEGIN")
        try:
            await self.connection.execute("""
                CREATE TABLE medical_records_new(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    appointment_id INTEGER NOT NULL,
                    diagnosis TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    file_path TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT NULL,
                    error_message TEXT DEFAULT NULL,

                    FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
                    UNIQUE(appointment_id, diagnosis)
                )
            """)

            await self.connection.execute("""
                INSERT INTO medical_records_new(
                    id, appointment_id, status, file_path, created_at, updated_at, error_message, diagnosis
                )
                SELECT
                    medical_records.id,
                    medical_records.appointment_id,
                    medical_records.status,
                    medical_records.file_path,
                    medical_records.created_at,
                    medical_records.updated_at,
                    medical_records.error_message,
                    COALESCE(appointments.purpose, '') AS diagnosis
                FROM medical_records
                LEFT JOIN appointments ON appointments.id = medical_records.appointment_id
            """)

            await self.connection.execute("DROP TABLE medical_records")
            await self.connection.execute("ALTER TABLE medical_records_new RENAME TO medical_records")
        except Exception:
            await self.connection.rollback()
            raise
        else:
            await self.connection.commit()

    async def create_pending(self, appointment_id: int, diagnosis: str, created_at: str) -> MedicalRecord:
        try:
            cursor = await self.connection.execute(
                """
                INSERT INTO medical_records(appointment_id, diagnosis, status, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (appointment_id, diagnosis, MedicalRecordStatus.PENDING.value, created_at),
            )
            await self.connection.commit()
        except aiosqlite.IntegrityError:
            # A row for this (appointment_id, diagnosis) pair already exists — this is a
            # deliberate race guard for concurrent trigger paths (e.g. a
            # completion job and a "get history" button press both trying
            # to create the pending row for the same appointment/diagnosis).
            # Treat "already exists" the same as "just created" so callers get a
            # uniform MedicalRecord back instead of a raw driver error.
            #
            # Roll back first: SQLite tolerates querying right after a failed
            # INSERT, but Postgres aborts the whole transaction on an
            # integrity error and refuses every subsequent statement until a
            # ROLLBACK — required for this fallback to keep working post-migration.
            await self.connection.rollback()
            existing = await self.get_by_appointment_and_diagnosis(appointment_id, diagnosis)
            if existing is not None:
                return existing
            raise

        record_id = cursor.lastrowid
        return await self._get_by_id(record_id)

    async def get_by_appointment_and_diagnosis(self, appointment_id: int, diagnosis: str) -> MedicalRecord | None:
        cursor = await self.connection.execute(
            MEDICAL_RECORD_SELECT + "\nWHERE appointment_id = ? AND diagnosis = ?",
            (appointment_id, diagnosis),
        )
        return self._row_to_medical_record(await cursor.fetchone())

    async def list_ready_by_appointment_id(self, appointment_id: int) -> list[MedicalRecord]:
        cursor = await self.connection.execute(
            MEDICAL_RECORD_SELECT + """
            WHERE appointment_id = ?
              AND status IN (?, ?)
              AND file_path IS NOT NULL
            """,
            (appointment_id, MedicalRecordStatus.READY.value, MedicalRecordStatus.READY_PARTIAL.value),
        )
        rows = await cursor.fetchall()
        return [self._row_to_medical_record(row) for row in rows]

    async def mark_generating(self, id: int, updated_at: str) -> None:
        await self.connection.execute(
            """
            UPDATE medical_records
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (MedicalRecordStatus.GENERATING.value, updated_at, id),
        )
        await self.connection.commit()

    async def mark_pending(self, id: int, updated_at: str) -> None:
        await self.connection.execute(
            """
            UPDATE medical_records
            SET status = ?, file_path = NULL, updated_at = ?
            WHERE id = ?
            """,
            (MedicalRecordStatus.PENDING.value, updated_at, id),
        )
        await self.connection.commit()

    async def mark_ready(self, id: int, file_path: str, partial: bool, updated_at: str) -> None:
        status = MedicalRecordStatus.READY_PARTIAL if partial else MedicalRecordStatus.READY
        await self.connection.execute(
            """
            UPDATE medical_records
            SET status = ?, file_path = ?, updated_at = ?
            WHERE id = ?
            """,
            (status.value, file_path, updated_at, id),
        )
        await self.connection.commit()

    async def mark_failed(self, id: int, error_message: str, updated_at: str) -> None:
        await self.connection.execute(
            """
            UPDATE medical_records
            SET status = ?, error_message = ?, updated_at = ?
            WHERE id = ?
            """,
            (MedicalRecordStatus.FAILED.value, error_message, updated_at, id),
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
            diagnosis=row[2],
            status=MedicalRecordStatus(row[3]),
            file_path=row[4],
            created_at=row[5],
            updated_at=row[6],
            error_message=row[7],
        )
