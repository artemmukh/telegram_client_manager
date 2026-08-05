import logging

import aiosqlite

from bot.exceptions.appointment_exceptions import SlotUnavailableError
from bot.models.appointment import Appointment
from bot.models.appointment_notification import AppointmentNotification
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy

logger = logging.getLogger(__name__)

SLOT_UNAVAILABLE_MESSAGE = {
    "ru": "Это время уже занято другой записью, выберите другое.",
    "uz": "Bu vaqt boshqa yozuv tomonidan band qilingan, boshqasini tanlang.",
}

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
    u.full_name AS client_full_name,
    u.phone AS client_phone,
    a.notification_message_id,
    a.proposed_datetime,
    a.proposal_message_id,
    a.proposed_by,
    a.admin_notification_message_id,
    d.full_name AS doctor_full_name,
    d.phone AS doctor_phone,
    a.price,
    s.is_doctor AS doctor_is_doctor,
    a.decided_by_user_id
FROM appointments a
LEFT JOIN clinics c ON c.id = a.clinic_id
LEFT JOIN users u ON u.id = a.client_id
LEFT JOIN users d ON d.id = a.admin_id
LEFT JOIN staff s ON s.telegram_user_id = d.telegram_user_id
"""


class AppointmentRepository:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection

    async def init(self, max_bookings_per_slot: int | None = None) -> None:
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
                decided_by_user_id INTEGER DEFAULT NULL,

                FOREIGN KEY(clinic_id) REFERENCES clinics(id) ON DELETE CASCADE,
                FOREIGN KEY(client_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(admin_id) REFERENCES users(id) ON DELETE SET NULL
            )
        """)

        # admin_tg_id is intentionally NOT re-added here: it is dead (never
        # read anywhere) and _rebuild_appointments_if_column_order_stale()
        # below drops it permanently. Re-adding it on every init() would
        # defeat that rebuild's idempotency guard (it keys on the full
        # column order, and a resurrected admin_tg_id would make every
        # subsequent init() look stale again).
        cursor = await self.connection.execute(
            "PRAGMA table_info(appointments)"
        )
        columns = {row[1] for row in await cursor.fetchall()}

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

        # Ensure decided_by_user_id column exists for existing databases
        if "decided_by_user_id" not in columns:
            await self.connection.execute(
                "ALTER TABLE appointments ADD COLUMN decided_by_user_id INTEGER DEFAULT NULL"
            )

        await self._rebuild_appointments_if_column_order_stale()

        await self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_appointments_clinic_datetime
            ON appointments(clinic_id, datetime)
        """)
        await self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_appointments_client
            ON appointments(client_id)
        """)

        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS appointment_notifications(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
            )
        """)
        await self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_appointment_notifications_appt_kind
            ON appointment_notifications(appointment_id, kind)
        """)

        if max_bookings_per_slot is None or max_bookings_per_slot == 1:
            # Drop the old (pre-widening) index name unconditionally, before the
            # duplicate check below, so it doesn't linger on an upgraded DB even
            # when duplicates are found and creation of the new index is skipped.
            await self.connection.execute(
                "DROP INDEX IF EXISTS idx_appointments_doctor_datetime_confirmed"
            )
            cursor = await self.connection.execute("""
                SELECT admin_id, datetime, COUNT(*)
                FROM appointments
                WHERE status IN ('pending', 'confirmed')
                GROUP BY admin_id, datetime
                HAVING COUNT(*) > 1
            """)
            duplicates = await cursor.fetchall()
            if duplicates:
                pairs = ", ".join(f"(admin_id={row[0]}, datetime={row[1]})" for row in duplicates)
                logger.error(
                    "Found duplicate pending/confirmed appointments for the same doctor/datetime, "
                    "skipping creation of idx_appointments_doctor_datetime_active "
                    "(double-booking protection is NOT active until this is resolved): %s",
                    pairs,
                )
            else:
                await self.connection.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_doctor_datetime_active
                    ON appointments(admin_id, datetime)
                    WHERE status IN ('pending', 'confirmed')
                """)
        else:
            # A prior init() call (old code, or a zb-style boot on this same
            # DB file) may have created the single-booking-per-slot unique
            # index. When max_bookings_per_slot allows multiple confirmed
            # bookings per slot, that index must not survive, or it will
            # keep hard-blocking additional confirmed bookings.
            await self.connection.execute(
                "DROP INDEX IF EXISTS idx_appointments_doctor_datetime_confirmed"
            )
            await self.connection.execute(
                "DROP INDEX IF EXISTS idx_appointments_doctor_datetime_active"
            )

        await self.connection.commit()

    # Target column order after rebuild (and already the order the fresh
    # CREATE TABLE above should produce, except it deliberately keeps
    # admin_tg_id and the legacy order so both fresh and legacy databases
    # flow through this single rebuild path).
    # ⚠️  CRITICAL: Any future phase that drops message_id columns
    # (notification_message_id, admin_notification_message_id, proposal_message_id)
    # must UPDATE this _TARGET_COLUMN_ORDER and all CREATE/INSERT/SELECT lists in
    # _rebuild_appointments_if_column_order_stale() synchronously in the same PR,
    # or the rebuild's staleness check will trigger on every startup and crash
    # trying to SELECT a non-existent column.
    _TARGET_COLUMN_ORDER = [
        "id", "clinic_id", "client_id", "admin_id", "datetime", "purpose", "price",
        "created_by", "status", "created_at", "status_updated_at",
        "notification_message_id", "proposed_datetime", "proposal_message_id",
        "proposed_by", "admin_notification_message_id", "decided_by_user_id",
    ]

    async def _rebuild_appointments_if_column_order_stale(self) -> None:
        # price must sit right after purpose (confirmed layout), and admin_tg_id
        # is dead (never read for production decisions) and must be dropped —
        # SQLite's ADD COLUMN cannot express either change, it only appends
        # columns at the end and cannot drop columns pre-3.35. A full table
        # rebuild is the only way to reorder/drop them. The staleness check
        # compares the full ordered column list against the target layout,
        # not just admin_tg_id's presence: admin_tg_id is no longer re-added
        # anywhere in init(), so a presence-only check would incorrectly skip
        # the rebuild for a genuinely ancient database that never carried
        # admin_tg_id at all, yet still has price appended at the end instead
        # of right after purpose (via the legacy ALTER ADD COLUMN guards
        # above, which can only append, never reorder).
        cursor = await self.connection.execute("PRAGMA table_info(appointments)")
        current_order = [row[1] for row in await cursor.fetchall()]

        if current_order == self._TARGET_COLUMN_ORDER:
            return

        await self.connection.commit()
        await self.connection.execute("PRAGMA foreign_keys = OFF")

        try:
            await self.connection.execute("BEGIN")

            await self.connection.execute("""
                CREATE TABLE appointments_new(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clinic_id INTEGER NOT NULL,
                    client_id INTEGER NOT NULL,
                    admin_id INTEGER DEFAULT NULL,
                    datetime TIMESTAMP NOT NULL,
                    purpose TEXT,
                    price REAL DEFAULT NULL,
                    created_by TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status_updated_at TIMESTAMP DEFAULT NULL,
                    notification_message_id INTEGER DEFAULT NULL,
                    proposed_datetime TIMESTAMP DEFAULT NULL,
                    proposal_message_id INTEGER DEFAULT NULL,
                    proposed_by TEXT DEFAULT NULL,
                    admin_notification_message_id INTEGER DEFAULT NULL,
                    decided_by_user_id INTEGER DEFAULT NULL,

                    FOREIGN KEY(clinic_id) REFERENCES clinics(id) ON DELETE CASCADE,
                    FOREIGN KEY(client_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(admin_id) REFERENCES users(id) ON DELETE SET NULL
                )
            """)

            await self.connection.execute("""
                INSERT INTO appointments_new (
                    id, clinic_id, client_id, admin_id, datetime, purpose, price,
                    created_by, status, created_at, status_updated_at,
                    notification_message_id, proposed_datetime, proposal_message_id,
                    proposed_by, admin_notification_message_id, decided_by_user_id
                )
                SELECT
                    id, clinic_id, client_id, admin_id, datetime, purpose, price,
                    created_by, status, created_at, status_updated_at,
                    notification_message_id, proposed_datetime, proposal_message_id,
                    proposed_by, admin_notification_message_id, decided_by_user_id
                FROM appointments
            """)

            await self.connection.execute("DROP TABLE appointments")
            await self.connection.execute("ALTER TABLE appointments_new RENAME TO appointments")

            fk_cursor = await self.connection.execute("PRAGMA foreign_key_check")
            violations = await fk_cursor.fetchall()
            if violations:
                raise RuntimeError(f"appointments rebuild produced FK violations: {violations}")

            await self.connection.commit()
        except Exception:
            await self.connection.execute("ROLLBACK")
            raise
        finally:
            await self.connection.execute("PRAGMA foreign_keys = ON")

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

    async def get_appointments_by_doctor_and_date(
        self,
        doctor_id: int,
        date: str,
        statuses: list[AppointmentStatus] | None = None,
    ) -> list[Appointment]:
        if statuses is None:
            statuses = [AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING]

        placeholders = ", ".join("?" for _ in statuses)
        cursor = await self.connection.execute(
            APPOINTMENT_SELECT + f"\nWHERE a.admin_id = ? AND a.datetime LIKE ? AND a.status IN ({placeholders})",
            (doctor_id, f"{date}%", *[status.value for status in statuses]),
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
                c.name AS clinic_name,
                u.full_name AS client_full_name, u.phone AS client_phone,
                a.notification_message_id, a.proposed_datetime, a.proposal_message_id,
                a.proposed_by, a.admin_notification_message_id,
                d.full_name AS doctor_full_name, d.phone AS doctor_phone,
                a.price, s.is_doctor AS doctor_is_doctor,
                a.decided_by_user_id
            FROM appointments a
            JOIN users u ON u.id = a.client_id
            LEFT JOIN clinics c ON c.id = a.clinic_id
            LEFT JOIN users d ON d.id = a.admin_id
            LEFT JOIN staff s ON s.telegram_user_id = d.telegram_user_id
            WHERE u.telegram_user_id = ?
            ORDER BY a.created_at DESC
            """,
            (telegram_user_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    async def create_appointment(self, appointment: Appointment) -> Appointment:
        try:
            cursor = await self.connection.execute(
                """
                INSERT INTO appointments(
                    clinic_id, client_id, admin_id,
                    datetime, purpose, created_by, status, created_at,
                    status_updated_at, notification_message_id
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
                    appointment.created_at,
                    appointment.created_at,
                    appointment.notification_message_id,
                ),
            )
            await self.connection.commit()
        except aiosqlite.IntegrityError as error:
            if self._is_slot_unique_violation(error):
                raise SlotUnavailableError(SLOT_UNAVAILABLE_MESSAGE) from error
            raise

        appointment_id = cursor.lastrowid
        created_appointment = await self.get_appointment_by_id(appointment_id)
        return created_appointment

    async def update_appointment(self, appointment_id: int, appointment: Appointment) -> None:
        try:
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
        except aiosqlite.IntegrityError as error:
            if self._is_slot_unique_violation(error):
                raise SlotUnavailableError(SLOT_UNAVAILABLE_MESSAGE) from error
            raise

    async def update_appointment_status(
        self, appointment_id: int, status: AppointmentStatus, status_updated_at: str
    ) -> None:
        try:
            await self.connection.execute(
                "UPDATE appointments SET status = ?, status_updated_at = ? WHERE id = ?",
                (status.value, status_updated_at, appointment_id),
            )
            await self.connection.commit()
        except aiosqlite.IntegrityError as error:
            if self._is_slot_unique_violation(error):
                raise SlotUnavailableError(SLOT_UNAVAILABLE_MESSAGE) from error
            raise

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

    async def try_confirm_or_reject_pending(
        self,
        appointment_id: int,
        new_status: AppointmentStatus,
        decided_by_user_id: int,
        status_updated_at: str,
    ) -> bool:
        # The status/proposed_datetime guard makes this a compare-and-set: it only
        # applies while the request is still a fresh pending one, so two staff
        # members racing to confirm/reject the same broadcast can't both succeed.
        sql = """
            UPDATE appointments
            SET status = ?, decided_by_user_id = ?, status_updated_at = ?
            WHERE id = ? AND status = 'pending' AND proposed_datetime IS NULL
        """
        params = (new_status.value, decided_by_user_id, status_updated_at, appointment_id)
        try:
            cursor = await self.connection.execute(sql, params)
            await self.connection.commit()
        except aiosqlite.IntegrityError as error:
            if self._is_slot_unique_violation(error):
                raise SlotUnavailableError(SLOT_UNAVAILABLE_MESSAGE) from error
            raise

        return cursor.rowcount > 0

    async def try_propose_new_datetime(
        self,
        appointment_id: int,
        new_datetime: str,
        decided_by_user_id: int,
        status_updated_at: str,
        expected_status: str,
    ) -> bool:
        # No longer stages a proposal awaiting a client callback -- the admin's new
        # datetime is committed immediately and the appointment is demoted to PENDING
        # (from either PENDING or CONFIRMED) so it awaits an ordinary reconfirmation,
        # expiring via the generic pending-expiry job like any other PENDING
        # appointment. Covers both a fresh admin proposal on a still-pending booking
        # request and an admin reschedule on an already-confirmed appointment, so the
        # target status is always 'pending' regardless of which one expected_status
        # was. expected_status pins the update to the exact prior status the caller
        # observed (true CAS) against a stale confirm/reject race; two admins racing
        # to propose on the same still-pending request now both succeed
        # (last-writer-wins on datetime), which is intended.
        sql = """
            UPDATE appointments
            SET datetime = ?, status = 'pending', decided_by_user_id = ?, status_updated_at = ?,
                proposed_datetime = NULL, proposed_by = NULL
            WHERE id = ?
                AND status = ?
        """
        params = (new_datetime, decided_by_user_id, status_updated_at, appointment_id, expected_status)
        try:
            cursor = await self.connection.execute(sql, params)
            await self.connection.commit()
        except aiosqlite.IntegrityError as error:
            if self._is_slot_unique_violation(error):
                raise SlotUnavailableError(SLOT_UNAVAILABLE_MESSAGE) from error
            raise

        return cursor.rowcount > 0

    async def try_update_own_pending_datetime(self, appointment_id: int, new_datetime: str) -> bool:
        # CAS for a client editing their own still-undecided self-booking request:
        # only applies while it's still pending, still client-created, and hasn't
        # picked up an admin proposal in the meantime, so a racing admin decision
        # (confirm/reject/propose) can't be silently overwritten by a stale client edit.
        sql = """
            UPDATE appointments
            SET datetime = ?
            WHERE id = ?
                AND status = 'pending'
                AND created_by = 'client'
                AND proposed_datetime IS NULL
        """
        params = (new_datetime, appointment_id)
        try:
            cursor = await self.connection.execute(sql, params)
            await self.connection.commit()
        except aiosqlite.IntegrityError as error:
            if self._is_slot_unique_violation(error):
                raise SlotUnavailableError(SLOT_UNAVAILABLE_MESSAGE) from error
            raise

        return cursor.rowcount > 0

    async def try_apply_new_datetime_immediately(
        self,
        appointment_id: int,
        new_datetime: str,
        decided_by_user_id: int,
        status_updated_at: str,
        expected_status: str,
    ) -> bool:
        # Used when the client has no linked Telegram account and therefore can never
        # confirm an admin proposal, so the new time is applied immediately instead of
        # waiting on a negotiation. Pins on expected_status the same way
        # try_propose_new_datetime does (true CAS), and still blocks racing in on top
        # of an in-progress admin proposal.
        sql = """
            UPDATE appointments
            SET datetime = ?, status = 'confirmed', decided_by_user_id = ?, status_updated_at = ?,
                proposed_datetime = NULL, proposed_by = NULL
            WHERE id = ?
                AND status = ?
                AND NOT (proposed_datetime IS NOT NULL AND proposed_by = 'admin')
        """
        params = (new_datetime, decided_by_user_id, status_updated_at, appointment_id, expected_status)
        try:
            cursor = await self.connection.execute(sql, params)
            await self.connection.commit()
        except aiosqlite.IntegrityError as error:
            if self._is_slot_unique_violation(error):
                raise SlotUnavailableError(SLOT_UNAVAILABLE_MESSAGE) from error
            raise

        return cursor.rowcount > 0

    async def try_resolve_client_reschedule(
        self,
        appointment_id: int,
        accept: bool,
        decided_by_user_id: int,
        status_updated_at: str,
        new_datetime: str | None = None,
    ) -> bool:
        # Replaces three separate commits (status, proposed_datetime, proposed_by)
        # with one atomic compare-and-set update.
        if accept:
            sql = """
                UPDATE appointments
                SET datetime = ?, status = 'confirmed',
                    proposed_datetime = NULL, proposed_by = NULL,
                    decided_by_user_id = ?, status_updated_at = ?
                WHERE id = ?
                    AND status NOT IN ('cancelled', 'completed', 'no_show', 'expired')
                    AND proposed_by = 'client' AND proposed_datetime IS NOT NULL
            """
            params = (new_datetime, decided_by_user_id, status_updated_at, appointment_id)
        else:
            sql = """
                UPDATE appointments
                SET status = 'cancelled',
                    proposed_datetime = NULL, proposed_by = NULL,
                    decided_by_user_id = ?, status_updated_at = ?
                WHERE id = ?
                    AND status NOT IN ('cancelled', 'completed', 'no_show', 'expired')
                    AND proposed_by = 'client' AND proposed_datetime IS NOT NULL
            """
            params = (decided_by_user_id, status_updated_at, appointment_id)

        try:
            cursor = await self.connection.execute(sql, params)
            await self.connection.commit()
        except aiosqlite.IntegrityError as error:
            if self._is_slot_unique_violation(error):
                raise SlotUnavailableError(SLOT_UNAVAILABLE_MESSAGE) from error
            raise

        return cursor.rowcount > 0

    async def try_complete_appointment(
        self, appointment_id: int, decided_by_user_id: int, status_updated_at: str
    ) -> bool:
        # This completion path previously had no guard at all; the status filter
        # closes that gap by ensuring a finalized appointment can't be re-completed.
        sql = """
            UPDATE appointments
            SET status = 'completed', decided_by_user_id = ?, status_updated_at = ?
            WHERE id = ? AND status NOT IN ('cancelled', 'completed', 'no_show', 'expired')
        """
        params = (decided_by_user_id, status_updated_at, appointment_id)
        cursor = await self.connection.execute(sql, params)
        await self.connection.commit()

        return cursor.rowcount > 0

    async def try_resolve_admin_proposal(
        self,
        appointment_id: int,
        accept: bool,
        status_updated_at: str,
        new_datetime: str | None = None,
    ) -> bool:
        # Single-recipient client flow (client accepting/rejecting the admin's
        # proposed datetime), so no decided_by_user_id write here.
        if accept:
            sql = """
                UPDATE appointments
                SET datetime = ?, status = 'confirmed', status_updated_at = ?,
                    proposed_datetime = NULL, proposed_by = NULL
                WHERE id = ?
                    AND status NOT IN ('cancelled', 'completed', 'no_show', 'expired')
                    AND proposed_by = 'admin' AND proposed_datetime IS NOT NULL
            """
            params = (new_datetime, status_updated_at, appointment_id)
        else:
            sql = """
                UPDATE appointments
                SET status = 'cancelled', status_updated_at = ?,
                    proposed_datetime = NULL, proposed_by = NULL
                WHERE id = ?
                    AND status NOT IN ('cancelled', 'completed', 'no_show', 'expired')
                    AND proposed_by = 'admin' AND proposed_datetime IS NOT NULL
            """
            params = (status_updated_at, appointment_id)

        try:
            cursor = await self.connection.execute(sql, params)
            await self.connection.commit()
        except aiosqlite.IntegrityError as error:
            if self._is_slot_unique_violation(error):
                raise SlotUnavailableError(SLOT_UNAVAILABLE_MESSAGE) from error
            raise

        return cursor.rowcount > 0

    async def add_appointment_notification(
        self, appointment_id: int, chat_id: int, message_id: int, kind: str
    ) -> None:
        await self.connection.execute(
            """
            INSERT INTO appointment_notifications(appointment_id, chat_id, message_id, kind)
            VALUES (?, ?, ?, ?)
            """,
            (appointment_id, chat_id, message_id, kind),
        )
        await self.connection.commit()

    async def get_appointment_notifications(
        self, appointment_id: int, kind: str
    ) -> list[AppointmentNotification]:
        cursor = await self.connection.execute(
            """
            SELECT id, appointment_id, chat_id, message_id, kind, created_at
            FROM appointment_notifications
            WHERE appointment_id = ? AND kind = ?
            ORDER BY id ASC
            """,
            (appointment_id, kind),
        )
        rows = await cursor.fetchall()
        return [
            AppointmentNotification(
                id=row[0],
                appointment_id=row[1],
                chat_id=row[2],
                message_id=row[3],
                kind=row[4],
                created_at=row[5],
            )
            for row in rows
        ]

    async def get_latest_notification_message_id(self, appointment_id: int, chat_id: int) -> int | None:
        cursor = await self.connection.execute(
            """
            SELECT message_id
            FROM appointment_notifications
            WHERE appointment_id = ? AND chat_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (appointment_id, chat_id),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

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

    async def get_appointments_in_range(
        self, clinic_id: int, doctor_id: int | None, start_datetime: str, end_datetime: str
    ) -> list[Appointment]:
        """Return every appointment (any status) for clinic_id (and doctor_id, if
        given) whose datetime falls in the half-open interval [start_datetime,
        end_datetime)."""
        conditions = ["a.clinic_id = ?", "a.datetime >= ?", "a.datetime < ?"]
        params = [clinic_id, start_datetime, end_datetime]

        if doctor_id is not None:
            conditions.append("a.admin_id = ?")
            params.append(doctor_id)

        sql = APPOINTMENT_SELECT + f"\nWHERE {' AND '.join(conditions)}\nORDER BY a.datetime ASC"
        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

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

    async def get_appointments_by_name_and_status_page(
        self,
        full_name: str,
        status: AppointmentStatus,
        page: int,
        clinic_id: int,
        doctor_id: int | None = None,
        per_page: int = 10,
        tab_bucket: bool = False,
    ) -> list[Appointment]:
        """Получить страницу результатов поиска по имени клиента с определённым
        статусом (для вкладок поиска по ФИО)"""
        parts = full_name.strip().title().split()
        if not parts:
            return []

        name_conditions = " OR ".join(["u.full_name LIKE ?"] * len(parts))
        name_params = [f"%{part}%" for part in parts]

        offset = (page - 1) * per_page
        order_by = self._status_order_by(status)

        status_condition, status_params = self._status_bucket_condition("a.", status, tab_bucket)
        conditions = [f"({name_conditions})", status_condition, "a.clinic_id = ?"]
        params = [*name_params, *status_params, clinic_id]

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

    async def count_appointments_by_name_and_status(
        self,
        full_name: str,
        status: AppointmentStatus,
        clinic_id: int,
        doctor_id: int | None = None,
        tab_bucket: bool = False,
    ) -> int:
        """Получить количество результатов поиска записей по имени клиента с определённым статусом"""
        parts = full_name.strip().title().split()
        if not parts:
            return 0

        name_conditions = " OR ".join(["u.full_name LIKE ?"] * len(parts))
        name_params = [f"%{part}%" for part in parts]

        status_condition, status_params = self._status_bucket_condition("a.", status, tab_bucket)
        conditions = [f"({name_conditions})", status_condition, "a.clinic_id = ?"]
        params = [*name_params, *status_params, clinic_id]

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
        tab_bucket: bool = False,
    ) -> list[Appointment]:
        """Получить страницу записей с определённым статусом (для вкладок админского списка)"""
        offset = (page - 1) * per_page
        order_by = self._status_order_by(status)

        status_condition, status_params = self._status_bucket_condition("a.", status, tab_bucket)
        conditions = [status_condition, "a.clinic_id = ?"]
        params = [*status_params, clinic_id]

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
        self, status: AppointmentStatus, clinic_id: int, doctor_id: int | None = None, tab_bucket: bool = False
    ) -> int:
        """Получить количество записей с определённым статусом"""
        status_condition, status_params = self._status_bucket_condition("", status, tab_bucket)
        conditions = [status_condition, "clinic_id = ?"]
        params = [*status_params, clinic_id]

        if doctor_id is not None:
            conditions.append("admin_id = ?")
            params.append(doctor_id)

        sql = f"SELECT COUNT(*) FROM appointments WHERE {' AND '.join(conditions)}"
        cursor = await self.connection.execute(sql, params)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def count_appointments_by_date_and_status(
        self,
        date_str: str,
        status: AppointmentStatus,
        clinic_id: int,
        doctor_id: int | None = None,
        tab_bucket: bool = False,
    ) -> int:
        """Получить количество записей на конкретную дату с определённым статусом (для календаря)"""
        status_condition, status_params = self._status_bucket_condition("", status, tab_bucket)
        conditions = ["date(datetime) = ?", status_condition, "clinic_id = ?"]
        params = [date_str, *status_params, clinic_id]

        if doctor_id is not None:
            conditions.append("admin_id = ?")
            params.append(doctor_id)

        sql = f"SELECT COUNT(*) FROM appointments WHERE {' AND '.join(conditions)}"
        cursor = await self.connection.execute(sql, params)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_appointments_by_date_and_status_page(
        self,
        date_str: str,
        status: AppointmentStatus,
        page: int,
        clinic_id: int,
        doctor_id: int | None = None,
        per_page: int = 10,
        tab_bucket: bool = False,
    ) -> list[Appointment]:
        """Получить страницу записей на конкретную дату с определённым статусом,
        отсортированную по времени приёма (для календаря)"""
        offset = (page - 1) * per_page

        status_condition, status_params = self._status_bucket_condition("a.", status, tab_bucket)
        conditions = ["date(a.datetime) = ?", status_condition, "a.clinic_id = ?"]
        params = [date_str, *status_params, clinic_id]

        if doctor_id is not None:
            conditions.append("a.admin_id = ?")
            params.append(doctor_id)

        sql = APPOINTMENT_SELECT + f"""
        WHERE {' AND '.join(conditions)}
        ORDER BY a.datetime ASC, a.id ASC
        LIMIT ? OFFSET ?
        """
        params.extend([per_page, offset])

        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()
        return [self._row_to_appointment(row) for row in rows]

    @staticmethod
    def _is_slot_unique_violation(error: aiosqlite.IntegrityError) -> bool:
        message = str(error)
        # Current SQLite (3.45.x) omits the index name from IntegrityError text and
        # reports "UNIQUE constraint failed: appointments.admin_id, appointments.datetime"
        # instead - the name check below is forward-defensive in case a future SQLite
        # version includes it.
        if "idx_appointments_doctor_datetime_active" in message:
            return True
        return (
            "UNIQUE constraint failed" in message
            and "admin_id" in message
            and "datetime" in message
        )

    @staticmethod
    def _status_bucket_condition(
        prefix: str, status: AppointmentStatus, tab_bucket: bool
    ) -> tuple[str, list]:
        """Build the status WHERE-condition for tab-bucketed pagination.

        When tab_bucket is False, behaves exactly like a plain `status = ?`.
        When True, a CONFIRMED+proposed_datetime appointment is reclassified
        into the PENDING bucket and excluded from the CONFIRMED bucket, while
        `status` itself stays untouched in the database.
        """
        if not tab_bucket:
            return f"{prefix}status = ?", [status.value]

        if status == AppointmentStatus.CONFIRMED:
            return f"{prefix}status = ? AND {prefix}proposed_datetime IS NULL", [status.value]

        if status == AppointmentStatus.PENDING:
            return (
                f"({prefix}status = ? OR ({prefix}status = 'confirmed' AND {prefix}proposed_datetime IS NOT NULL))",
                [status.value],
            )

        return f"{prefix}status = ?", [status.value]

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
            client_full_name=row[11],
            client_phone=row[12],
            notification_message_id=row[13],
            proposed_datetime=row[14],
            proposal_message_id=row[15],
            proposed_by=CreatedBy(row[16]) if row[16] else None,
            admin_notification_message_id=row[17],
            doctor_full_name=row[18],
            doctor_phone=row[19],
            price=row[20],
            doctor_is_doctor=bool(row[21]) if row[21] is not None else None,
            decided_by_user_id=row[22],
        )
