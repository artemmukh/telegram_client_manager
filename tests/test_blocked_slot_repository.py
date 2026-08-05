import aiosqlite
import pytest
import pytest_asyncio

from bot.models.blocked_slot import BlockedSlot
from bot.repositories.blocked_slot_repository import BlockedSlotRepository


@pytest_asyncio.fixture
async def blocked_slot_repo(tmp_path):
    connection = await aiosqlite.connect(tmp_path / "test.db")
    repo = BlockedSlotRepository(connection)
    await repo.init()

    yield repo

    await connection.close()


def _block(
    clinic_id=1, staff_id=42, start="2026-08-10 09:00", end="2026-08-10 11:00",
    reason="Vacation", created_by=1, created_at="2026-08-05 08:00:00",
):
    return BlockedSlot(
        clinic_id=clinic_id, staff_id=staff_id, start_datetime=start, end_datetime=end,
        reason=reason, created_by=created_by, created_at=created_at,
    )


@pytest.mark.asyncio
async def test_create_block_and_get_block_by_id_return_same_block(blocked_slot_repo):
    created = await blocked_slot_repo.create_block(_block())

    fetched = await blocked_slot_repo.get_block_by_id(created.id)

    assert fetched == created
    assert fetched.clinic_id == 1
    assert fetched.staff_id == 42
    assert fetched.reason == "Vacation"
    assert fetched.cancelled_at is None


@pytest.mark.asyncio
async def test_get_block_by_id_returns_none_when_missing(blocked_slot_repo):
    fetched = await blocked_slot_repo.get_block_by_id(9999)

    assert fetched is None


@pytest.mark.asyncio
async def test_get_blocks_covering_range_matches_block_starting_exactly_at_range_start(blocked_slot_repo):
    """A slot range that opens exactly where the block opens overlaps it: both
    intervals are half-open, so [09:00, 09:15) and [09:00, 10:00) share 09:00."""
    await blocked_slot_repo.create_block(
        _block(start="2026-08-10 09:00", end="2026-08-10 10:00")
    )

    matches = await blocked_slot_repo.get_blocks_covering_range(
        1, 42, "2026-08-10 09:00", "2026-08-10 09:15"
    )

    assert len(matches) == 1


@pytest.mark.asyncio
async def test_get_blocks_covering_range_range_starting_at_block_end_does_not_match(blocked_slot_repo):
    """A slot range that opens exactly where the block closes does not overlap
    it: [10:00, 10:15) and [09:00, 10:00) only touch."""
    await blocked_slot_repo.create_block(
        _block(start="2026-08-10 09:00", end="2026-08-10 10:00")
    )

    matches = await blocked_slot_repo.get_blocks_covering_range(
        1, 42, "2026-08-10 10:00", "2026-08-10 10:15"
    )

    assert matches == []


@pytest.mark.asyncio
async def test_get_blocks_covering_range_back_to_back_ranges_do_not_overlap(blocked_slot_repo):
    await blocked_slot_repo.create_block(
        _block(start="2026-08-10 09:00", end="2026-08-10 10:00")
    )

    matches = await blocked_slot_repo.get_blocks_covering_range(
        1, 42, "2026-08-10 10:00", "2026-08-10 11:00"
    )

    assert matches == []


@pytest.mark.asyncio
async def test_get_blocks_covering_range_finds_clinic_wide_block_for_specific_staff(blocked_slot_repo):
    await blocked_slot_repo.create_block(
        _block(staff_id=None, start="2026-08-10 09:00", end="2026-08-10 11:00")
    )

    matches = await blocked_slot_repo.get_blocks_covering_range(
        1, 42, "2026-08-10 09:30", "2026-08-10 09:30"
    )

    assert len(matches) == 1
    assert matches[0].staff_id is None


@pytest.mark.asyncio
async def test_get_blocks_covering_range_ignores_other_clinics_block(blocked_slot_repo):
    await blocked_slot_repo.create_block(
        _block(clinic_id=2, start="2026-08-10 09:00", end="2026-08-10 11:00")
    )

    matches = await blocked_slot_repo.get_blocks_covering_range(
        1, 42, "2026-08-10 09:30", "2026-08-10 09:30"
    )

    assert matches == []


@pytest.mark.asyncio
async def test_get_blocks_covering_range_ignores_other_doctors_block(blocked_slot_repo):
    await blocked_slot_repo.create_block(
        _block(staff_id=99, start="2026-08-10 09:00", end="2026-08-10 11:00")
    )

    matches = await blocked_slot_repo.get_blocks_covering_range(
        1, 42, "2026-08-10 09:30", "2026-08-10 09:30"
    )

    assert matches == []


@pytest.mark.asyncio
async def test_get_active_blocks_by_clinic_excludes_cancelled(blocked_slot_repo):
    active = await blocked_slot_repo.create_block(_block(start="2026-08-10 09:00", end="2026-08-10 10:00"))
    cancelled = await blocked_slot_repo.create_block(_block(start="2026-08-11 09:00", end="2026-08-11 10:00"))
    await blocked_slot_repo.cancel_block(cancelled.id, "2026-08-05 08:00:00")

    active_blocks = await blocked_slot_repo.get_active_blocks_by_clinic(1)

    assert [b.id for b in active_blocks] == [active.id]


@pytest.mark.asyncio
async def test_get_active_blocks_by_clinic_scopes_by_clinic_id(blocked_slot_repo):
    await blocked_slot_repo.create_block(_block(clinic_id=1))
    await blocked_slot_repo.create_block(_block(clinic_id=2))

    active_blocks = await blocked_slot_repo.get_active_blocks_by_clinic(1)

    assert len(active_blocks) == 1
    assert active_blocks[0].clinic_id == 1


@pytest.mark.asyncio
async def test_cancel_block_first_call_succeeds_and_sets_cancelled_at(blocked_slot_repo):
    block = await blocked_slot_repo.create_block(_block())

    cancelled = await blocked_slot_repo.cancel_block(block.id, "2026-08-05 08:00:00")

    assert cancelled is True
    fetched = await blocked_slot_repo.get_block_by_id(block.id)
    assert fetched.cancelled_at == "2026-08-05 08:00:00"


@pytest.mark.asyncio
async def test_cancel_block_second_call_fails_and_does_not_overwrite(blocked_slot_repo):
    block = await blocked_slot_repo.create_block(_block())
    await blocked_slot_repo.cancel_block(block.id, "2026-08-05 08:00:00")

    second_attempt = await blocked_slot_repo.cancel_block(block.id, "2026-08-06 09:00:00")

    assert second_attempt is False
    fetched = await blocked_slot_repo.get_block_by_id(block.id)
    assert fetched.cancelled_at == "2026-08-05 08:00:00"


@pytest.mark.asyncio
async def test_cancel_block_returns_false_when_block_missing(blocked_slot_repo):
    cancelled = await blocked_slot_repo.cancel_block(9999, "2026-08-05 08:00:00")

    assert cancelled is False


@pytest.mark.asyncio
async def test_init_adds_missing_cancelled_at_column_on_legacy_table(tmp_path):
    connection = await aiosqlite.connect(tmp_path / "legacy.db")
    await connection.execute("""
        CREATE TABLE blocked_slots(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_id INTEGER NOT NULL,
            staff_id INTEGER,
            start_datetime TEXT NOT NULL,
            end_datetime TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    await connection.commit()

    repo = BlockedSlotRepository(connection)
    await repo.init()

    block = await repo.create_block(_block())
    fetched = await repo.get_block_by_id(block.id)

    assert fetched.cancelled_at is None
    cancelled = await repo.cancel_block(block.id, "2026-08-05 08:00:00")
    assert cancelled is True

    await connection.close()


@pytest.mark.asyncio
async def test_init_is_idempotent(blocked_slot_repo):
    await blocked_slot_repo.init()
    await blocked_slot_repo.init()

    block = await blocked_slot_repo.create_block(_block())
    fetched = await blocked_slot_repo.get_block_by_id(block.id)

    assert fetched == block
