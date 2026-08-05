import aiosqlite

from bot.models.blocked_slot import BlockedSlot


class BlockedSlotRepository:
    def __init__(self, connection: aiosqlite.Connection):
        self.connection = connection

    async def init(self) -> None:
        await self.connection.execute("""
            CREATE TABLE IF NOT EXISTS blocked_slots(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clinic_id INTEGER NOT NULL,
                staff_id INTEGER,
                start_datetime TEXT NOT NULL,
                end_datetime TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                cancelled_at TEXT
            )
        """)

        cursor = await self.connection.execute("PRAGMA table_info(blocked_slots)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "cancelled_at" not in columns:
            await self.connection.execute(
                "ALTER TABLE blocked_slots ADD COLUMN cancelled_at TEXT DEFAULT NULL"
            )

        await self.connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_blocked_slots_clinic_active
            ON blocked_slots(clinic_id, cancelled_at)
        """)

        await self.connection.commit()

    async def create_block(self, block: BlockedSlot) -> BlockedSlot:
        cursor = await self.connection.execute(
            """
            INSERT INTO blocked_slots(
                clinic_id, staff_id, start_datetime, end_datetime,
                reason, created_by, created_at, cancelled_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                block.clinic_id,
                block.staff_id,
                block.start_datetime,
                block.end_datetime,
                block.reason,
                block.created_by,
                block.created_at,
                block.cancelled_at,
            ),
        )
        await self.connection.commit()

        block_id = cursor.lastrowid
        return await self.get_block_by_id(block_id)

    async def get_active_blocks_by_clinic(self, clinic_id: int) -> list[BlockedSlot]:
        cursor = await self.connection.execute(
            """
            SELECT id, clinic_id, staff_id, start_datetime, end_datetime,
                   reason, created_by, created_at, cancelled_at
            FROM blocked_slots
            WHERE clinic_id = ? AND cancelled_at IS NULL
            ORDER BY start_datetime ASC
            """,
            (clinic_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_blocked_slot(row) for row in rows]

    async def get_blocks_covering_range(
        self,
        clinic_id: int,
        staff_id: int | None,
        start_datetime: str,
        end_datetime: str,
    ) -> list[BlockedSlot]:
        # staff_id=None here means "check clinic-wide blocks only" (e.g. a
        # clinic-level operation with no specific doctor in context) -- it is
        # NOT a wildcard. Because staff_id = NULL never matches in SQL, the
        # `(staff_id = ? OR staff_id IS NULL)` predicate below collapses to
        # matching only rows where the block's own staff_id is NULL, so
        # doctor-specific blocks are invisible to a staff_id=None query. When
        # checking a specific doctor's availability, callers must pass that
        # doctor's id to also pick up clinic-wide blocks alongside their own.
        #
        # Interval overlap convention: a block occupies [start_datetime,
        # end_datetime) -- start inclusive, end EXCLUSIVE -- matching the
        # half-open convention used for appointment slots elsewhere in this
        # codebase. Standard half-open overlap is
        #     block.start_datetime < query_end AND block.end_datetime > query_start
        # which is correct for a proper range query (query_end > query_start)
        # but breaks for the degenerate point-in-time query used at booking
        # time (start_datetime == end_datetime == the exact slot instant):
        # a slot landing exactly on a block's start instant would fail
        # `block.start_datetime < query_end` (both equal), silently letting a
        # double-booking through. The `OR start_datetime = ?` disjunct below
        # special-cases only that degenerate query: it is a no-op for a
        # proper range (if block.start == query_start and query_start <
        # query_end, then block.start < query_end already holds), so it adds
        # no false positives for range-vs-range conflict checks (e.g.
        # back-to-back blocks that just touch are correctly NOT flagged as
        # overlapping) while still catching a booking that lands exactly on
        # a block's start.
        cursor = await self.connection.execute(
            """
            SELECT id, clinic_id, staff_id, start_datetime, end_datetime,
                   reason, created_by, created_at, cancelled_at
            FROM blocked_slots
            WHERE clinic_id = ?
                AND cancelled_at IS NULL
                AND (staff_id = ? OR staff_id IS NULL)
                AND end_datetime > ?
                AND (start_datetime < ? OR start_datetime = ?)
            ORDER BY start_datetime ASC
            """,
            (clinic_id, staff_id, start_datetime, end_datetime, start_datetime),
        )
        rows = await cursor.fetchall()
        return [self._row_to_blocked_slot(row) for row in rows]

    async def get_block_by_id(self, block_id: int) -> BlockedSlot | None:
        cursor = await self.connection.execute(
            """
            SELECT id, clinic_id, staff_id, start_datetime, end_datetime,
                   reason, created_by, created_at, cancelled_at
            FROM blocked_slots
            WHERE id = ?
            """,
            (block_id,),
        )
        return self._row_to_blocked_slot(await cursor.fetchone())

    async def cancel_block(self, block_id: int, cancelled_at: str) -> bool:
        cursor = await self.connection.execute(
            "UPDATE blocked_slots SET cancelled_at = ? WHERE id = ? AND cancelled_at IS NULL",
            (cancelled_at, block_id),
        )
        await self.connection.commit()
        return cursor.rowcount > 0

    def _row_to_blocked_slot(self, row) -> BlockedSlot | None:
        if row is None:
            return None

        return BlockedSlot(
            id=row[0],
            clinic_id=row[1],
            staff_id=row[2],
            start_datetime=row[3],
            end_datetime=row[4],
            reason=row[5],
            created_by=row[6],
            created_at=row[7],
            cancelled_at=row[8],
        )
