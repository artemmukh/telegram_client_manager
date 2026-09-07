"""Tests for MedicalRecordRepository: create/read/status-update round trip,
the (appointment_id, diagnosis) composite-key uniqueness (create_pending is
idempotent under a race for the same pair, but independent per distinct
diagnosis), the ready/pending/generating filtering of
list_ready_by_appointment_id, and the legacy-schema upgrade migration."""

import aiosqlite
import pytest
import pytest_asyncio

from bot.repositories.medical_record_repository import MedicalRecordRepository
from bot.utils.medical_record_enums import MedicalRecordStatus

TS = "2026-07-26 15:00:00"
TS2 = "2026-07-26 15:05:00"


@pytest_asyncio.fixture
async def medical_record_repo():
    # No PRAGMA foreign_keys=ON here: the medical_records table's FK to
    # appointments(id) is only enforced when foreign_keys is explicitly turned
    # on (SQLite default is off), so these tests can use bare appointment_id
    # integers without also standing up an appointments table.
    connection = await aiosqlite.connect(":memory:")
    repo = MedicalRecordRepository(connection)
    await repo.init()
    yield repo
    await connection.close()


@pytest_asyncio.fixture
async def linked_medical_record_repo():
    """Repository fixture with the appointment/user joins used by client pages.

    Keep the existing bare ``medical_record_repo`` fixture unchanged: most
    legacy repository tests intentionally do not need an appointments table.
    """
    connection = await aiosqlite.connect(":memory:")
    await connection.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, full_name TEXT NOT NULL)")
    await connection.execute("""
        CREATE TABLE appointments(
            id INTEGER PRIMARY KEY,
            clinic_id INTEGER NOT NULL,
            client_id INTEGER NOT NULL,
            admin_id INTEGER,
            datetime TIMESTAMP NOT NULL,
            purpose TEXT
        )
    """)
    await connection.executemany(
        "INSERT INTO users(id, full_name) VALUES (?, ?)",
        [(7, "Доктор Семёнов"), (8, "Доктор Ким")],
    )
    await connection.executemany(
        """
        INSERT INTO appointments(id, clinic_id, client_id, admin_id, datetime, purpose)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (101, 1, 10, 7, "2026-09-01 10:00:00", "Кариес 11"),
            (102, 1, 10, 8, "2026-09-02 10:00:00", "Кариес 12"),
            (103, 1, 10, 7, "2026-09-03 10:00:00", "Кариес 13"),
            (104, 1, 10, 7, "2026-09-04 10:00:00", "Кариес 14"),
            (105, 2, 10, 7, "2026-09-05 10:00:00", "Кариес 15"),
            (106, 1, 11, 7, "2026-09-06 10:00:00", "Кариес 16"),
        ],
    )
    await connection.commit()

    repo = MedicalRecordRepository(connection)
    await repo.init()
    for appointment_id, diagnosis, created_at in [
        (101, "Документ 101", "2026-09-01 12:00:00"),
        (102, "Документ 102", "2026-09-02 12:00:00"),
        (103, "Документ 103", "2026-09-03 12:00:00"),
        (104, "Документ 104", "2026-09-04 12:00:00"),
        (105, "Документ 105", "2026-09-05 12:00:00"),
        (106, "Документ 106", "2026-09-06 12:00:00"),
    ]:
        record = await repo.create_pending(appointment_id, diagnosis, created_at)
        await repo.mark_ready(record.id, f"/tmp/{record.id}.docx", partial=False, updated_at=created_at)

    yield repo
    await connection.close()


@pytest.mark.asyncio
async def test_create_pending_then_read_round_trip(medical_record_repo):
    created = await medical_record_repo.create_pending(
        appointment_id=42, diagnosis="Кариес 37", created_at=TS,
    )

    assert created.appointment_id == 42
    assert created.diagnosis == "Кариес 37"
    assert created.status is MedicalRecordStatus.PENDING
    assert created.file_path is None
    assert created.created_at == TS
    assert created.id is not None

    fetched = await medical_record_repo.get_by_appointment_and_diagnosis(42, "Кариес 37")
    assert fetched == created


@pytest.mark.asyncio
async def test_mark_generating_updates_status(medical_record_repo):
    record = await medical_record_repo.create_pending(appointment_id=1, diagnosis="Консультация", created_at=TS)

    await medical_record_repo.mark_generating(record.id, TS2)

    updated = await medical_record_repo.get_by_appointment_and_diagnosis(1, "Консультация")
    assert updated.status is MedicalRecordStatus.GENERATING
    assert updated.updated_at == TS2


@pytest.mark.asyncio
async def test_mark_ready_sets_status_and_file_path(medical_record_repo):
    record = await medical_record_repo.create_pending(appointment_id=1, diagnosis="Консультация", created_at=TS)
    await medical_record_repo.mark_generating(record.id, TS2)

    await medical_record_repo.mark_ready(record.id, "/tmp/medical_card_1.docx", partial=False, updated_at=TS2)

    updated = await medical_record_repo.get_by_appointment_and_diagnosis(1, "Консультация")
    assert updated.status is MedicalRecordStatus.READY
    assert updated.file_path == "/tmp/medical_card_1.docx"
    assert updated.updated_at == TS2


@pytest.mark.asyncio
async def test_mark_ready_partial_sets_ready_partial_status(medical_record_repo):
    record = await medical_record_repo.create_pending(appointment_id=1, diagnosis="Консультация", created_at=TS)

    await medical_record_repo.mark_ready(record.id, "/tmp/medical_card_1.docx", partial=True, updated_at=TS2)

    updated = await medical_record_repo.get_by_appointment_and_diagnosis(1, "Консультация")
    assert updated.status is MedicalRecordStatus.READY_PARTIAL
    assert updated.file_path == "/tmp/medical_card_1.docx"


@pytest.mark.asyncio
async def test_mark_pending_resets_status_and_clears_file_path(medical_record_repo):
    record = await medical_record_repo.create_pending(appointment_id=1, diagnosis="Консультация", created_at=TS)
    await medical_record_repo.mark_ready(record.id, "/tmp/medical_card_1.docx", partial=False, updated_at=TS2)

    await medical_record_repo.mark_pending(record.id, TS2)

    updated = await medical_record_repo.get_by_appointment_and_diagnosis(1, "Консультация")
    assert updated.status is MedicalRecordStatus.PENDING
    assert updated.file_path is None


@pytest.mark.asyncio
async def test_mark_failed_sets_status_and_error_message(medical_record_repo):
    record = await medical_record_repo.create_pending(appointment_id=1, diagnosis="Консультация", created_at=TS)

    await medical_record_repo.mark_failed(record.id, "Ollama unavailable", TS2)

    updated = await medical_record_repo.get_by_appointment_and_diagnosis(1, "Консультация")
    assert updated.status is MedicalRecordStatus.FAILED
    assert updated.error_message == "Ollama unavailable"


@pytest.mark.asyncio
async def test_create_pending_is_idempotent_for_same_appointment_id_and_diagnosis(medical_record_repo):
    """A second create_pending() for an (appointment_id, diagnosis) pair that
    already has a row (e.g. a completion job and a "get history" button press
    racing) must return the existing record instead of raising an
    IntegrityError or duplicating it."""
    first = await medical_record_repo.create_pending(appointment_id=7, diagnosis="Кариес 37", created_at=TS)
    second = await medical_record_repo.create_pending(appointment_id=7, diagnosis="Кариес 37", created_at=TS2)

    assert first.id == second.id
    assert second.appointment_id == 7

    fetched = await medical_record_repo.get_by_appointment_and_diagnosis(7, "Кариес 37")
    assert fetched.id == first.id


@pytest.mark.asyncio
async def test_create_pending_idempotency_preserves_already_advanced_status(medical_record_repo):
    """If the existing row already advanced past PENDING (e.g. GENERATING) by
    the time a racing create_pending() call lands, the uniqueness fallback must
    return the CURRENT row, not silently reset it back to pending."""
    record = await medical_record_repo.create_pending(appointment_id=7, diagnosis="Кариес 37", created_at=TS)
    await medical_record_repo.mark_generating(record.id, TS2)

    again = await medical_record_repo.create_pending(appointment_id=7, diagnosis="Кариес 37", created_at=TS2)

    assert again.id == record.id
    assert again.status is MedicalRecordStatus.GENERATING


@pytest.mark.asyncio
async def test_create_pending_with_different_diagnosis_creates_independent_row(medical_record_repo):
    """A second create_pending() for the same appointment_id but a *different*
    diagnosis (the appointment's purpose was edited since the last
    generation) must create its own new row, leaving the first untouched."""
    first = await medical_record_repo.create_pending(appointment_id=7, diagnosis="Кариес 37", created_at=TS)
    await medical_record_repo.mark_ready(first.id, "/tmp/first.docx", partial=False, updated_at=TS2)

    second = await medical_record_repo.create_pending(appointment_id=7, diagnosis="Пульпит 46", created_at=TS2)

    assert second.id != first.id
    assert second.status is MedicalRecordStatus.PENDING
    assert second.file_path is None

    first_reloaded = await medical_record_repo.get_by_appointment_and_diagnosis(7, "Кариес 37")
    assert first_reloaded.status is MedicalRecordStatus.READY
    assert first_reloaded.file_path == "/tmp/first.docx"


@pytest.mark.asyncio
async def test_list_ready_by_appointment_id_only_returns_ready_rows_with_file_path(medical_record_repo):
    pending = await medical_record_repo.create_pending(appointment_id=9, diagnosis="Консультация", created_at=TS)
    generating = await medical_record_repo.create_pending(appointment_id=9, diagnosis="Кариес 37", created_at=TS)
    await medical_record_repo.mark_generating(generating.id, TS2)
    ready = await medical_record_repo.create_pending(appointment_id=9, diagnosis="Пульпит 46", created_at=TS)
    await medical_record_repo.mark_ready(ready.id, "/tmp/ready.docx", partial=False, updated_at=TS2)
    ready_partial = await medical_record_repo.create_pending(appointment_id=9, diagnosis="Периодонтит", created_at=TS)
    await medical_record_repo.mark_ready(ready_partial.id, "/tmp/partial.docx", partial=True, updated_at=TS2)

    documents = await medical_record_repo.list_ready_by_appointment_id(9)

    document_ids = {d.id for d in documents}
    assert document_ids == {ready.id, ready_partial.id}
    assert [document.id for document in documents] == [ready_partial.id, ready.id]
    assert pending.id not in document_ids
    assert generating.id not in document_ids


@pytest.mark.asyncio
async def test_get_by_id_returns_record_and_none_for_unknown_id(linked_medical_record_repo):
    record = await linked_medical_record_repo.get_by_id(4)

    assert record is not None
    assert record.id == 4
    assert record.appointment_id == 104
    assert await linked_medical_record_repo.get_by_id(999) is None


@pytest.mark.asyncio
async def test_list_by_appointment_id_pages_newest_first_with_stable_id_tiebreaker(
    linked_medical_record_repo,
):
    second = await linked_medical_record_repo.create_pending(
        appointment_id=103,
        diagnosis="Повторный документ 103",
        created_at="2026-09-03 12:00:00",
    )
    await linked_medical_record_repo.mark_ready(
        second.id,
        f"/tmp/{second.id}.docx",
        partial=False,
        updated_at="2026-09-03 12:00:00",
    )

    page = await linked_medical_record_repo.list_by_appointment_id(103, limit=1, offset=0)
    next_page = await linked_medical_record_repo.list_by_appointment_id(103, limit=1, offset=1)

    assert [item.id for item in page] == [second.id]
    assert [item.id for item in next_page] == [3]
    assert await linked_medical_record_repo.count_by_appointment_id(103) == 2


@pytest.mark.asyncio
async def test_list_by_client_id_pages_only_records_visible_to_clinic_and_doctor(
    linked_medical_record_repo,
):
    items = await linked_medical_record_repo.list_by_client_id(
        client_id=10, clinic_id=1, doctor_id=7, limit=2, offset=0,
    )

    assert [item.id for item in items] == [4, 3]
    assert all(item.appointment_datetime for item in items)
    assert all(item.doctor_full_name for item in items)
    assert [item.appointment_datetime for item in items] == [
        "2026-09-04 10:00:00",
        "2026-09-03 10:00:00",
    ]
    assert [item.doctor_full_name for item in items] == ["Доктор Семёнов", "Доктор Семёнов"]
    assert await linked_medical_record_repo.count_by_client_id(10, 1, doctor_id=7) == 3


@pytest.mark.asyncio
async def test_list_by_client_id_applies_clinic_scope_and_offset_without_doctor_filter(
    linked_medical_record_repo,
):
    page = await linked_medical_record_repo.list_by_client_id(
        client_id=10, clinic_id=1, doctor_id=None, limit=2, offset=2,
    )

    assert [item.id for item in page] == [2, 1]
    assert await linked_medical_record_repo.count_by_client_id(10, 1, doctor_id=None) == 4


@pytest.mark.asyncio
async def test_delete_by_id_returns_bool_and_removes_only_existing_record(linked_medical_record_repo):
    assert await linked_medical_record_repo.delete_by_id(4) is True
    assert await linked_medical_record_repo.get_by_id(4) is None
    assert await linked_medical_record_repo.delete_by_id(4) is False
    assert await linked_medical_record_repo.get_by_id(3) is not None


@pytest.mark.asyncio
async def test_init_is_idempotent_on_a_fresh_database(medical_record_repo):
    """Running init() again on an already-current-schema database must be a
    no-op that neither errors nor loses data."""
    created = await medical_record_repo.create_pending(appointment_id=5, diagnosis="Кариес 37", created_at=TS)

    await medical_record_repo.init()

    fetched = await medical_record_repo.get_by_appointment_and_diagnosis(5, "Кариес 37")
    assert fetched.id == created.id
    assert fetched.diagnosis == "Кариес 37"


@pytest.mark.asyncio
async def test_legacy_schema_migration_backfills_diagnosis_from_appointment_purpose():
    """Simulates upgrading a pre-existing DB created before the
    appointment_id/diagnosis composite key: a single-column
    UNIQUE(appointment_id) constraint, no diagnosis column. init() must
    detect the legacy auto-index, rebuild the table onto the composite key,
    and backfill diagnosis from the linked appointment's purpose without
    losing any existing row."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute("""
            CREATE TABLE appointments(
                id INTEGER PRIMARY KEY,
                purpose TEXT
            )
        """)
        await connection.execute(
            "INSERT INTO appointments(id, purpose) VALUES (?, ?)", (42, "Кариес 37 зуба"),
        )
        await connection.execute("""
            CREATE TABLE medical_records(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                file_path TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT NULL,

                FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
            )
        """)
        await connection.execute(
            """
            INSERT INTO medical_records(appointment_id, status, file_path, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (42, MedicalRecordStatus.READY.value, "/tmp/legacy.docx", TS),
        )
        await connection.commit()

        repo = MedicalRecordRepository(connection)
        await repo.init()

        migrated = await repo.get_by_appointment_and_diagnosis(42, "Кариес 37 зуба")
        assert migrated is not None
        assert migrated.status is MedicalRecordStatus.READY
        assert migrated.file_path == "/tmp/legacy.docx"
        assert migrated.created_at == TS
        assert migrated.diagnosis == "Кариес 37 зуба"

        # The whole point of the migration: a second, distinct diagnosis for
        # the same appointment_id can now be created independently, which the
        # old single-column UNIQUE(appointment_id) constraint would have
        # rejected as a duplicate key.
        second = await repo.create_pending(appointment_id=42, diagnosis="Пульпит 46", created_at=TS2)
        assert second.id != migrated.id

        # Re-running init() again must be a no-op (the composite index no
        # longer matches the legacy shape) and must not lose either row.
        await repo.init()
        still_there = await repo.get_by_appointment_and_diagnosis(42, "Кариес 37 зуба")
        assert still_there is not None
        assert still_there.id == migrated.id
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_legacy_schema_migration_recovers_from_a_leftover_scratch_table():
    """Simulates a prior migration attempt that crashed after creating
    medical_records_new but before the DROP/RENAME completed (or before the
    surrounding transaction was even wrapped). init() must not choke on the
    leftover scratch table -- it drops it and rebuilds cleanly, losing
    neither the pre-existing row nor duplicating it."""
    connection = await aiosqlite.connect(":memory:")
    try:
        await connection.execute("""
            CREATE TABLE appointments(
                id INTEGER PRIMARY KEY,
                purpose TEXT
            )
        """)
        await connection.execute(
            "INSERT INTO appointments(id, purpose) VALUES (?, ?)", (42, "Кариес 37 зуба"),
        )
        await connection.execute("""
            CREATE TABLE medical_records(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending',
                file_path TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT NULL,

                FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
            )
        """)
        await connection.execute(
            """
            INSERT INTO medical_records(appointment_id, status, file_path, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (42, MedicalRecordStatus.READY.value, "/tmp/legacy.docx", TS),
        )
        # Leftover scratch table from a simulated prior crashed migration
        # attempt -- deliberately populated with stale/bogus data to prove
        # init() discards it rather than merging or reading from it.
        await connection.execute("""
            CREATE TABLE medical_records_new(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                appointment_id INTEGER NOT NULL,
                diagnosis TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                file_path TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT NULL,
                error_message TEXT DEFAULT NULL,

                UNIQUE(appointment_id, diagnosis)
            )
        """)
        await connection.execute(
            """
            INSERT INTO medical_records_new(appointment_id, diagnosis, status, file_path, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (999, "stale scratch row", MedicalRecordStatus.FAILED.value, None, TS),
        )
        await connection.commit()

        repo = MedicalRecordRepository(connection)
        await repo.init()

        migrated = await repo.get_by_appointment_and_diagnosis(42, "Кариес 37 зуба")
        assert migrated is not None
        assert migrated.status is MedicalRecordStatus.READY
        assert migrated.file_path == "/tmp/legacy.docx"
        assert migrated.diagnosis == "Кариес 37 зуба"

        # The stale scratch table's bogus row must not have leaked into the
        # final medical_records table.
        assert await repo.get_by_appointment_and_diagnosis(999, "stale scratch row") is None

        second = await repo.create_pending(appointment_id=42, diagnosis="Пульпит 46", created_at=TS2)
        assert second.id != migrated.id
    finally:
        await connection.close()
