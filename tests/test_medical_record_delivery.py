"""Tests for deliver_medical_record, the shared "Получить историю болезни"
button handler used by both the admin and client callback routers.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.utils.medical_record_delivery import deliver_medical_record
from bot.models.medical_record import MedicalRecord
from bot.utils.medical_record_enums import MedicalRecordStatus


def _callback_query():
    callback_query = MagicMock()
    callback_query.message.answer_document = AsyncMock()
    callback_query.answer = AsyncMock()
    return callback_query


def _service(record, needs_generation=False):
    service = MagicMock()
    service.get_or_generate = AsyncMock(return_value=(record, needs_generation))
    return service


def _scheduler():
    scheduler = MagicMock()
    scheduler.schedule_medical_record_generation = AsyncMock()
    return scheduler


@pytest.mark.asyncio
async def test_ready_record_sends_document_and_answers_without_alert():
    record = MedicalRecord(
        id=1, appointment_id=10, status=MedicalRecordStatus.READY, file_path="/data/medical_card_10.docx",
    )
    callback_query = _callback_query()
    scheduler = _scheduler()

    await deliver_medical_record(callback_query, _service(record), scheduler, 10)

    callback_query.message.answer_document.assert_awaited_once()
    sent_document = callback_query.message.answer_document.call_args.args[0]
    assert sent_document.path == "/data/medical_card_10.docx"
    callback_query.answer.assert_awaited_once_with()
    scheduler.schedule_medical_record_generation.assert_not_awaited()


@pytest.mark.asyncio
async def test_ready_partial_record_sends_document_too():
    record = MedicalRecord(
        id=1, appointment_id=10, status=MedicalRecordStatus.READY_PARTIAL, file_path="/data/medical_card_10.docx",
    )
    callback_query = _callback_query()
    scheduler = _scheduler()

    await deliver_medical_record(callback_query, _service(record), scheduler, 10)

    callback_query.message.answer_document.assert_awaited_once()
    sent_document = callback_query.message.answer_document.call_args.args[0]
    assert sent_document.path == "/data/medical_card_10.docx"


@pytest.mark.parametrize("status", [MedicalRecordStatus.PENDING, MedicalRecordStatus.GENERATING])
@pytest.mark.asyncio
async def test_pending_or_generating_record_shows_alert_without_sending_document(status):
    record = MedicalRecord(id=1, appointment_id=10, status=status, file_path=None)
    callback_query = _callback_query()
    scheduler = _scheduler()

    await deliver_medical_record(callback_query, _service(record), scheduler, 10)

    callback_query.message.answer_document.assert_not_awaited()
    callback_query.answer.assert_awaited_once_with(
        "Документ ещё готовится, попробуйте через пару минут", show_alert=True,
    )
    scheduler.schedule_medical_record_generation.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_record_shows_alert_without_sending_document():
    record = MedicalRecord(
        id=1, appointment_id=10, status=MedicalRecordStatus.FAILED, file_path=None, error_message="boom",
    )
    callback_query = _callback_query()
    scheduler = _scheduler()

    await deliver_medical_record(callback_query, _service(record), scheduler, 10)

    callback_query.message.answer_document.assert_not_awaited()
    callback_query.answer.assert_awaited_once_with(
        "Документ ещё готовится, попробуйте через пару минут", show_alert=True,
    )


@pytest.mark.asyncio
async def test_no_prior_record_triggers_fallback_generation_and_shows_alert():
    """Edge case per the design doc: appointment is COMPLETED but no
    medical_records row exists yet (generation was never triggered). The
    service creates a pending row and signals needs_generation=True; the
    delivery helper must kick off generation via schedule_medical_record_generation
    as a fallback and still tell the caller to check back later."""
    fallback_record = MedicalRecord(id=1, appointment_id=10, status=MedicalRecordStatus.PENDING, file_path=None)
    callback_query = _callback_query()
    scheduler = _scheduler()

    await deliver_medical_record(callback_query, _service(fallback_record, needs_generation=True), scheduler, 10)

    scheduler.schedule_medical_record_generation.assert_awaited_once_with(10)
    callback_query.message.answer_document.assert_not_awaited()
    callback_query.answer.assert_awaited_once_with(
        "Документ ещё готовится, попробуйте через пару минут", show_alert=True,
    )
