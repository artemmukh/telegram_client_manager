"""Tests for deliver_medical_record and add_medical_record_document, the
shared "Получить историю болезни" / "➕ Добавить документ" button handlers
used by both the admin and client callback routers.

deliver_medical_record: send every already-ready document for the
appointment (one message per diagnosis) via get_ready_documents(); only if
none exist yet fall back to a synchronous generate() call. A document whose
file went missing from disk is regenerated in place (via the service's
ensure_file_exists), keyed by its own diagnosis (not the appointment's
current purpose), before being sent.

add_medical_record_document: always generate()s for the given diagnosis
(idempotent for an unchanged diagnosis, a fresh independent record for a
changed one) and sends the result -- the two idempotency tests below drive
a REAL MedicalRecordService + fake repo (not a mock) since that behavior is
a service/repo property, not something a mocked service can exhibit.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.utils.medical_record_delivery import (
    FAILURE_MESSAGE,
    add_medical_record_document,
    deliver_medical_record,
)
from bot.models.appointment import Appointment
from bot.models.medical_record import MedicalRecord
from bot.models.user import User
from bot.services.medical_record.medical_record_management import MedicalRecordService
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.medical_record_enums import MedicalRecordStatus
from bot.utils.role import Role

from tests.conftest import FakeAppointmentManagement, FakeChatLLM

_DEFAULT = object()


def _real_service(fake_medical_record_repo, appointment, client, monkeypatch, create_docx_mock):
    monkeypatch.setattr(
        "bot.services.medical_record.medical_record_management.create_docx", create_docx_mock,
    )
    return MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment, client), FakeChatLLM(response={
            "complaints": "Жалоб нет", "diseases": "Не выявлено", "examination": "Без особенностей",
            "treatment": "Не требуется", "tooth_map": [],
        }), instance="zb",
    )


def _appointment(appointment_id=10, purpose="Кариес 37"):
    return Appointment(
        clinic_id=1, client_id=7, datetime="2026-07-10 14:30", purpose=purpose,
        created_by=CreatedBy.ADMIN, status=AppointmentStatus.COMPLETED, id=appointment_id,
    )


def _client(client_id=7):
    return User(
        full_name="Иванов Иван Иванович", phone="+998901234567", role=Role.CLIENT, ID=client_id,
        gender="male", birth_date="1990-05-01",
    )


def _callback_query():
    callback_query = MagicMock()
    callback_query.message.answer_document = AsyncMock()
    callback_query.message.answer = AsyncMock()
    callback_query.answer = AsyncMock()
    return callback_query


def _service(ready_documents=None, generate_result=None, ensure_file_exists_result=_DEFAULT):
    """ensure_file_exists defaults to returning whatever record it was handed
    unchanged (i.e. the file is present on disk) -- tests exercising the
    "file missing, must regenerate" branch override it explicitly (or replace
    it outright with a per-record side_effect), since that regeneration
    policy now lives entirely inside the (mocked) service, not in the
    handler."""
    service = MagicMock()
    service.get_ready_documents = AsyncMock(return_value=list(ready_documents or []))
    service.generate = AsyncMock(return_value=generate_result)
    if ensure_file_exists_result is _DEFAULT:
        service.ensure_file_exists = AsyncMock(side_effect=lambda record: record)
    else:
        service.ensure_file_exists = AsyncMock(return_value=ensure_file_exists_result)
    return service


@pytest.mark.asyncio
async def test_ready_record_sends_document_and_answers_without_alert(tmp_path):
    file_path = tmp_path / "medical_card_10.docx"
    file_path.write_bytes(b"")
    record = MedicalRecord(
        id=1, appointment_id=10, diagnosis="Кариес 37", status=MedicalRecordStatus.READY, file_path=str(file_path),
    )
    callback_query = _callback_query()
    service = _service(ready_documents=[record])

    await deliver_medical_record(callback_query, service, 10)

    service.get_ready_documents.assert_awaited_once_with(10)
    callback_query.message.answer_document.assert_awaited_once()
    sent_document = callback_query.message.answer_document.call_args.args[0]
    assert sent_document.path == str(file_path)
    callback_query.answer.assert_awaited_once_with()
    service.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_ready_partial_record_sends_document_too(tmp_path):
    file_path = tmp_path / "medical_card_10.docx"
    file_path.write_bytes(b"")
    record = MedicalRecord(
        id=1, appointment_id=10, diagnosis="Кариес 37", status=MedicalRecordStatus.READY_PARTIAL,
        file_path=str(file_path),
    )
    callback_query = _callback_query()
    service = _service(ready_documents=[record])

    await deliver_medical_record(callback_query, service, 10)

    callback_query.message.answer_document.assert_awaited_once()
    sent_document = callback_query.message.answer_document.call_args.args[0]
    assert sent_document.path == str(file_path)


@pytest.mark.asyncio
async def test_multiple_ready_documents_each_sent_as_a_separate_message(tmp_path):
    """Different diagnoses for the same appointment each get their own
    document -- the regression this whole rework was designed to fix
    (previously a changed diagnosis would overwrite the earlier document
    instead of producing an independent one to send alongside it)."""
    first_path = tmp_path / "medical_card_a.docx"
    first_path.write_bytes(b"")
    second_path = tmp_path / "medical_card_b.docx"
    second_path.write_bytes(b"")
    first = MedicalRecord(
        id=1, appointment_id=10, diagnosis="Кариес 37", status=MedicalRecordStatus.READY, file_path=str(first_path),
    )
    second = MedicalRecord(
        id=2, appointment_id=10, diagnosis="Пульпит 46", status=MedicalRecordStatus.READY, file_path=str(second_path),
    )
    callback_query = _callback_query()
    service = _service(ready_documents=[first, second])

    await deliver_medical_record(callback_query, service, 10)

    assert callback_query.message.answer_document.await_count == 2
    sent_paths = {call.args[0].path for call in callback_query.message.answer_document.call_args_list}
    assert sent_paths == {str(first_path), str(second_path)}


@pytest.mark.asyncio
async def test_generating_record_is_never_sent_because_it_is_excluded_from_ready_documents(tmp_path):
    """Regression test for the original spam bug: a record still in
    GENERATING status must never be handed to the delivery helper as if it
    were ready. Asserts the actual contract that fixed the bug -- delivery
    only ever sends what get_ready_documents() (which filters out
    pending/generating rows) returns, never something it fetches itself via
    get_by_appointment_id/get_latest_by_appointment_id."""
    callback_query = _callback_query()
    service = _service(ready_documents=[])
    generating_record = MedicalRecord(
        id=1, appointment_id=10, diagnosis="Кариес 37", status=MedicalRecordStatus.GENERATING, file_path=None,
    )
    service.generate = AsyncMock(return_value=generating_record)

    await deliver_medical_record(callback_query, service, 10)

    service.get_ready_documents.assert_awaited_once_with(10)
    callback_query.message.answer_document.assert_not_awaited()
    callback_query.message.answer.assert_awaited_once_with("Документ ещё готовится, попробуйте через пару минут")


@pytest.mark.asyncio
async def test_no_ready_documents_triggers_synchronous_generation_and_sends_result(tmp_path):
    file_path = tmp_path / "medical_card_10.docx"
    file_path.write_bytes(b"")
    generated = MedicalRecord(
        id=1, appointment_id=10, diagnosis="Кариес 37", status=MedicalRecordStatus.READY, file_path=str(file_path),
    )
    callback_query = _callback_query()
    service = _service(ready_documents=[], generate_result=generated)

    await deliver_medical_record(callback_query, service, 10)

    callback_query.answer.assert_awaited_once_with("Готовим документ, это может занять до минуты", show_alert=True)
    service.generate.assert_awaited_once_with(10)
    callback_query.message.answer_document.assert_awaited_once()
    sent_document = callback_query.message.answer_document.call_args.args[0]
    assert sent_document.path == str(file_path)


@pytest.mark.asyncio
async def test_generation_returning_failed_shows_failure_message():
    record = MedicalRecord(
        id=1, appointment_id=10, status=MedicalRecordStatus.FAILED, file_path=None, error_message="boom",
    )
    callback_query = _callback_query()
    service = _service(ready_documents=[], generate_result=record)

    await deliver_medical_record(callback_query, service, 10)

    callback_query.message.answer_document.assert_not_awaited()
    callback_query.message.answer.assert_awaited_once_with(FAILURE_MESSAGE["ru"])


@pytest.mark.asyncio
async def test_generation_returning_none_shows_failure_message():
    callback_query = _callback_query()
    service = _service(ready_documents=[], generate_result=None)

    await deliver_medical_record(callback_query, service, 10)

    callback_query.message.answer_document.assert_not_awaited()
    callback_query.message.answer.assert_awaited_once_with(FAILURE_MESSAGE["ru"])


@pytest.mark.asyncio
async def test_ready_record_with_missing_file_triggers_regeneration_before_sending(tmp_path):
    """The DB row says ready but the .docx was deleted from disk (e.g. manual
    cleanup). The regeneration policy itself (reset to pending, regenerate
    keyed by its own diagnosis) now lives entirely in
    MedicalRecordService.ensure_file_exists (covered in isolation by
    test_medical_record_service.py) -- delivery must simply send whatever
    ensure_file_exists hands back."""
    regenerated_path = tmp_path / "medical_card_10_v2.docx"
    regenerated_path.write_bytes(b"")
    record = MedicalRecord(
        id=1, appointment_id=10, diagnosis="Кариес 37", status=MedicalRecordStatus.READY, file_path="/gone.docx",
    )
    regenerated = MedicalRecord(
        id=1, appointment_id=10, diagnosis="Кариес 37", status=MedicalRecordStatus.READY,
        file_path=str(regenerated_path),
    )
    callback_query = _callback_query()
    service = _service(ready_documents=[record], ensure_file_exists_result=regenerated)

    await deliver_medical_record(callback_query, service, 10)

    service.ensure_file_exists.assert_awaited_once_with(record)
    callback_query.message.answer_document.assert_awaited_once()
    sent_document = callback_query.message.answer_document.call_args.args[0]
    assert sent_document.path == str(regenerated_path)


@pytest.mark.asyncio
async def test_one_record_failing_regeneration_does_not_block_the_rest_of_the_batch(tmp_path):
    """Per the docstring guarantee, a document whose file went missing and
    fails to regenerate must not abort the whole batch -- the other
    already-ready documents in the same call must still be sent, with a
    failure message reported only for the broken one."""
    good_path = tmp_path / "medical_card_good.docx"
    good_path.write_bytes(b"")
    good_record = MedicalRecord(
        id=1, appointment_id=10, diagnosis="Кариес 37", status=MedicalRecordStatus.READY, file_path=str(good_path),
    )
    broken_record = MedicalRecord(
        id=2, appointment_id=10, diagnosis="Пульпит 46", status=MedicalRecordStatus.READY,
        file_path="/gone.docx",
    )
    callback_query = _callback_query()
    service = _service(ready_documents=[good_record, broken_record])
    service.ensure_file_exists = AsyncMock(
        side_effect=lambda record: good_record if record.id == good_record.id else None,
    )

    await deliver_medical_record(callback_query, service, 10)

    assert callback_query.message.answer_document.await_count == 1
    sent_document = callback_query.message.answer_document.call_args.args[0]
    assert sent_document.path == str(good_path)
    callback_query.message.answer.assert_awaited_once_with(FAILURE_MESSAGE["ru"])


@pytest.mark.asyncio
async def test_ready_record_with_missing_file_and_failed_regeneration_reports_failure(tmp_path):
    record = MedicalRecord(
        id=1, appointment_id=10, diagnosis="Кариес 37", status=MedicalRecordStatus.READY, file_path="/gone.docx",
    )
    callback_query = _callback_query()
    service = _service(ready_documents=[record], ensure_file_exists_result=None)

    await deliver_medical_record(callback_query, service, 10)

    callback_query.message.answer_document.assert_not_awaited()
    callback_query.message.answer.assert_awaited_once_with(FAILURE_MESSAGE["ru"])


# --- add_medical_record_document ("➕ Добавить документ") ---

@pytest.mark.asyncio
async def test_add_medical_record_document_generates_for_the_given_diagnosis_and_sends_it(tmp_path):
    file_path = tmp_path / "medical_card_10.docx"
    file_path.write_bytes(b"")
    generated = MedicalRecord(
        id=1, appointment_id=10, diagnosis="Кариес 37", status=MedicalRecordStatus.READY, file_path=str(file_path),
    )
    callback_query = _callback_query()
    service = _service(generate_result=generated)

    await add_medical_record_document(callback_query, service, 10, "Кариес 37")

    callback_query.answer.assert_awaited_once_with("Готовим документ, это может занять до минуты", show_alert=True)
    service.generate.assert_awaited_once_with(10, "Кариес 37")
    callback_query.message.answer_document.assert_awaited_once()
    sent_document = callback_query.message.answer_document.call_args.args[0]
    assert sent_document.path == str(file_path)


@pytest.mark.asyncio
async def test_add_medical_record_document_is_idempotent_for_an_unchanged_diagnosis(
    fake_medical_record_repo, monkeypatch, tmp_path,
):
    """Calling the "add document" action twice for the same diagnosis must
    not produce a second record/file -- driven against a REAL
    MedicalRecordService (not a mock) so the assertions actually exercise
    generate()'s (appointment_id, diagnosis) idempotency instead of just
    echoing back a pre-configured mock return value."""
    appointment = _appointment(purpose="Кариес 37")
    client = _client()
    def _write_and_return(data, tooth_map, output_path, template_path):
        file_path = tmp_path / f"{output_path.stem}.docx"
        file_path.write_bytes(b"")
        return str(file_path)

    create_docx_mock = AsyncMock(side_effect=_write_and_return)
    service = _real_service(fake_medical_record_repo, appointment, client, monkeypatch, create_docx_mock)
    callback_query = _callback_query()

    await add_medical_record_document(callback_query, service, 10, "Кариес 37")
    await add_medical_record_document(callback_query, service, 10, "Кариес 37")

    assert len(fake_medical_record_repo.records) == 1
    assert create_docx_mock.await_count == 1
    assert callback_query.message.answer_document.await_count == 2
    sent_paths = {call.args[0].path for call in callback_query.message.answer_document.call_args_list}
    assert len(sent_paths) == 1


@pytest.mark.asyncio
async def test_add_medical_record_document_with_changed_diagnosis_creates_an_independent_second_document(
    fake_medical_record_repo, monkeypatch, tmp_path,
):
    """A changed diagnosis must produce its own independent record/file
    alongside the first, leaving the first record's status/file_path
    untouched -- again driven against a real service+fake repo."""
    appointment = _appointment(purpose="Кариес 37")
    client = _client()
    def _write_and_return(data, tooth_map, output_path, template_path):
        file_path = tmp_path / f"{output_path.stem}.docx"
        file_path.write_bytes(b"")
        return str(file_path)

    create_docx_mock = AsyncMock(side_effect=_write_and_return)
    service = _real_service(fake_medical_record_repo, appointment, client, monkeypatch, create_docx_mock)
    callback_query = _callback_query()

    await add_medical_record_document(callback_query, service, 10, "Кариес 37")
    first_record = next(r for r in fake_medical_record_repo.records if r.diagnosis == "Кариес 37")
    first_file_path = first_record.file_path
    first_status = first_record.status

    appointment.purpose = "Пульпит 46"
    await add_medical_record_document(callback_query, service, 10, "Пульпит 46")

    assert len(fake_medical_record_repo.records) == 2
    first_reloaded = await fake_medical_record_repo.get_by_appointment_and_diagnosis(10, "Кариес 37")
    assert first_reloaded.file_path == first_file_path
    assert first_reloaded.status == first_status
    second_reloaded = await fake_medical_record_repo.get_by_appointment_and_diagnosis(10, "Пульпит 46")
    assert second_reloaded is not None
    assert second_reloaded.status is MedicalRecordStatus.READY
    assert second_reloaded.file_path != first_file_path
    assert callback_query.message.answer_document.await_count == 2


@pytest.mark.asyncio
async def test_add_medical_record_document_generation_returning_failed_shows_failure_message():
    record = MedicalRecord(
        id=1, appointment_id=10, status=MedicalRecordStatus.FAILED, file_path=None, error_message="boom",
    )
    callback_query = _callback_query()
    service = _service(generate_result=record)

    await add_medical_record_document(callback_query, service, 10, "Кариес 37")

    callback_query.message.answer_document.assert_not_awaited()
    callback_query.message.answer.assert_awaited_once_with(FAILURE_MESSAGE["ru"])


@pytest.mark.asyncio
async def test_add_medical_record_document_generation_returning_none_shows_failure_message():
    callback_query = _callback_query()
    service = _service(generate_result=None)

    await add_medical_record_document(callback_query, service, 10, "Кариес 37")

    callback_query.message.answer_document.assert_not_awaited()
    callback_query.message.answer.assert_awaited_once_with(FAILURE_MESSAGE["ru"])
