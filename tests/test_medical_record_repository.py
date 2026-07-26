"""Tests for MedicalRecordRepository: create/read/status-update round trip and
appointment_id uniqueness (create_pending is idempotent under a race)."""

import aiosqlite
import pytest
import pytest_asyncio

from bot.repositories.medical_record_repository import MedicalRecordRepository
from bot.utils.medical_record_enums import MedicalRecordStatus


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


@pytest.mark.asyncio
async def test_create_pending_then_read_round_trip(medical_record_repo):
    created = await medical_record_repo.create_pending(appointment_id=42)

    assert created.appointment_id == 42
    assert created.status is MedicalRecordStatus.PENDING
    assert created.file_path is None
    assert created.id is not None

    fetched = await medical_record_repo.get_by_appointment_id(42)
    assert fetched == created


@pytest.mark.asyncio
async def test_get_by_appointment_id_returns_none_when_missing(medical_record_repo):
    assert await medical_record_repo.get_by_appointment_id(999) is None


@pytest.mark.asyncio
async def test_mark_generating_updates_status(medical_record_repo):
    record = await medical_record_repo.create_pending(appointment_id=1)

    await medical_record_repo.mark_generating(record.id)

    updated = await medical_record_repo.get_by_appointment_id(1)
    assert updated.status is MedicalRecordStatus.GENERATING


@pytest.mark.asyncio
async def test_mark_ready_sets_status_and_file_path(medical_record_repo):
    record = await medical_record_repo.create_pending(appointment_id=1)
    await medical_record_repo.mark_generating(record.id)

    await medical_record_repo.mark_ready(record.id, "/tmp/medical_card_1.docx", partial=False)

    updated = await medical_record_repo.get_by_appointment_id(1)
    assert updated.status is MedicalRecordStatus.READY
    assert updated.file_path == "/tmp/medical_card_1.docx"


@pytest.mark.asyncio
async def test_mark_ready_partial_sets_ready_partial_status(medical_record_repo):
    record = await medical_record_repo.create_pending(appointment_id=1)

    await medical_record_repo.mark_ready(record.id, "/tmp/medical_card_1.docx", partial=True)

    updated = await medical_record_repo.get_by_appointment_id(1)
    assert updated.status is MedicalRecordStatus.READY_PARTIAL
    assert updated.file_path == "/tmp/medical_card_1.docx"


@pytest.mark.asyncio
async def test_mark_pending_resets_status_and_clears_file_path(medical_record_repo):
    record = await medical_record_repo.create_pending(appointment_id=1)
    await medical_record_repo.mark_ready(record.id, "/tmp/medical_card_1.docx", partial=False)

    await medical_record_repo.mark_pending(record.id)

    updated = await medical_record_repo.get_by_appointment_id(1)
    assert updated.status is MedicalRecordStatus.PENDING
    assert updated.file_path is None


@pytest.mark.asyncio
async def test_mark_failed_sets_status_and_error_message(medical_record_repo):
    record = await medical_record_repo.create_pending(appointment_id=1)

    await medical_record_repo.mark_failed(record.id, "Ollama unavailable")

    updated = await medical_record_repo.get_by_appointment_id(1)
    assert updated.status is MedicalRecordStatus.FAILED
    assert updated.error_message == "Ollama unavailable"


@pytest.mark.asyncio
async def test_create_pending_is_idempotent_for_same_appointment_id(medical_record_repo):
    """A second create_pending() for an appointment_id that already has a row
    (e.g. a completion job and a "get history" button press racing) must return
    the existing record instead of raising an IntegrityError or duplicating it."""
    first = await medical_record_repo.create_pending(appointment_id=7)
    second = await medical_record_repo.create_pending(appointment_id=7)

    assert first.id == second.id
    assert second.appointment_id == 7

    fetched = await medical_record_repo.get_by_appointment_id(7)
    assert fetched.id == first.id


@pytest.mark.asyncio
async def test_create_pending_idempotency_preserves_already_advanced_status(medical_record_repo):
    """If the existing row already advanced past PENDING (e.g. GENERATING) by
    the time a racing create_pending() call lands, the uniqueness fallback must
    return the CURRENT row, not silently reset it back to pending."""
    record = await medical_record_repo.create_pending(appointment_id=7)
    await medical_record_repo.mark_generating(record.id)

    again = await medical_record_repo.create_pending(appointment_id=7)

    assert again.id == record.id
    assert again.status is MedicalRecordStatus.GENERATING
