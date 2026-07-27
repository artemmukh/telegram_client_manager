"""Tests for MedicalRecordService.generate()/get_ready_documents()/
mark_for_regeneration()/ensure_file_exists() and the JSON-key ->
template-placeholder mapping.

generate() is keyed by (appointment_id, diagnosis): idempotent for an
unchanged diagnosis (including a GENERATING row that is still fresh), but a
changed diagnosis (appointment.purpose edited since the last generation)
always creates its own new record and document instead of overwriting the
previous one. A GENERATING row whose updated_at is older than
STALE_GENERATING_MINUTES is treated as abandoned (e.g. a crashed process)
and regenerated instead of blocking forever.

ensure_file_exists() covers the "file present on disk" vs "file went
missing, regenerate keyed by the record's own diagnosis" policy used by the
"get document" button's _send_document helper.

create_docx is monkeypatched rather than actually rendering a .docx (no
existing precedent in this repo for testing document-producing code end to
end -- other services stub the rendering step and assert on the data handed
to it, e.g. how price_list/geolocation tests stub FSInputFile rather than
touching the real files).
"""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from bot.exceptions.medical_record_exceptions import MedicalRecordGenerationError
from bot.models.appointment import Appointment
from bot.models.medical_record import MedicalRecord
from bot.models.user import User
from bot.services.document_generator.pydocx import OUTPUT_DIR
from bot.services.medical_record.medical_record_management import (
    DIAGNOSIS_SEGMENT_MAX_LENGTH,
    PATH_SEGMENT_MAX_LENGTH,
    STALE_GENERATING_MINUTES,
    MedicalRecordService,
)
from bot.services.utils.date_parser import get_current_tashkent_datetime, get_current_tashkent_time
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.medical_record_enums import MedicalRecordStatus
from bot.utils.role import Role

from tests.conftest import LLM_RESPONSE, FakeAppointmentManagement, FakeChatLLM


def _appointment(appointment_id=1, client_id=7, purpose="Средний кариес 37 зуба"):
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        datetime="2026-07-10 14:30",
        purpose=purpose,
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.COMPLETED,
        id=appointment_id,
    )


def _client(client_id=7):
    return User(
        full_name="Иванов Иван Иванович",
        phone="+998901234567",
        role=Role.CLIENT,
        ID=client_id,
        gender="male",
        birth_date="1990-05-01",
    )


@pytest.mark.asyncio
async def test_generate_success_creates_docx_and_marks_ready(fake_medical_record_repo, monkeypatch):
    appointment = _appointment()
    client = _client()
    chat_llm = FakeChatLLM(response=LLM_RESPONSE)
    service = MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment, client), chat_llm, instance="zb",
    )

    create_docx_mock = AsyncMock(return_value="/data/history_of_illness/generated/medical_card_1.docx")
    monkeypatch.setattr(
        "bot.services.medical_record.medical_record_management.create_docx", create_docx_mock,
    )

    record = await service.generate(appointment.id)

    assert record.status is MedicalRecordStatus.READY
    assert record.file_path == "/data/history_of_illness/generated/medical_card_1.docx"
    assert record.diagnosis == appointment.purpose
    assert len(chat_llm.calls) == 1

    create_docx_mock.assert_awaited_once()
    data_arg, tooth_map_arg, output_path_arg, template_path_arg = create_docx_mock.call_args.args
    assert tooth_map_arg == LLM_RESPONSE["tooth_map"]
    assert output_path_arg == service._build_output_path(appointment, client, appointment.purpose, record.id)
    assert template_path_arg == "data/history_of_illness/medical_card_wisdom_tooth.docx"
    assert data_arg["complaints"] == LLM_RESPONSE["complaints"]
    assert data_arg["diseases"] == LLM_RESPONSE["diseases"]
    assert data_arg["examination"] == LLM_RESPONSE["examination"]
    assert data_arg["diagnosis"] == appointment.purpose
    assert data_arg["treatment"] == LLM_RESPONSE["treatment"]
    assert data_arg["full_name"] == client.full_name
    assert data_arg["phone"] == client.phone
    assert "tooth_map" not in data_arg


@pytest.mark.asyncio
async def test_generate_falls_back_to_empty_ai_fields_when_llm_fails(fake_medical_record_repo, monkeypatch):
    appointment = _appointment()
    client = _client()
    chat_llm = FakeChatLLM(error=MedicalRecordGenerationError("Ollama unavailable"))
    service = MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment, client), chat_llm, instance="zb",
    )

    create_docx_mock = AsyncMock(return_value="/data/history_of_illness/generated/medical_card_1.docx")
    monkeypatch.setattr(
        "bot.services.medical_record.medical_record_management.create_docx", create_docx_mock,
    )

    record = await service.generate(appointment.id)

    assert record.status is MedicalRecordStatus.READY_PARTIAL
    assert record.file_path == "/data/history_of_illness/generated/medical_card_1.docx"

    data_arg, tooth_map_arg = create_docx_mock.call_args.args[0], create_docx_mock.call_args.args[1]
    assert data_arg["complaints"] == ""
    assert data_arg["diseases"] == ""
    assert data_arg["examination"] == ""
    assert data_arg["diagnosis"] == appointment.purpose
    assert data_arg["treatment"] == ""
    assert "tooth_map" not in data_arg
    assert tooth_map_arg == []


@pytest.mark.parametrize("status", [
    MedicalRecordStatus.READY,
    MedicalRecordStatus.READY_PARTIAL,
    MedicalRecordStatus.GENERATING,
])
@pytest.mark.asyncio
async def test_generate_is_idempotent_when_already_generated_or_in_flight(
    fake_medical_record_repo, monkeypatch, status,
):
    appointment = _appointment()
    client = _client()
    existing = MedicalRecord(
        id=5, appointment_id=appointment.id, diagnosis=appointment.purpose, status=status,
        file_path="/existing/path.docx",
        # Fresh updated_at: keeps the GENERATING case out of the stale-row
        # branch (see test_generate_regenerates_a_stale_generating_row_*),
        # so this test exercises the normal in-flight idempotency path.
        updated_at=get_current_tashkent_time(),
    )
    fake_medical_record_repo.records.append(existing)

    chat_llm = FakeChatLLM(response=LLM_RESPONSE)
    service = MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment, client), chat_llm, instance="zb",
    )

    create_docx_mock = AsyncMock()
    monkeypatch.setattr(
        "bot.services.medical_record.medical_record_management.create_docx", create_docx_mock,
    )

    result = await service.generate(appointment.id)

    assert result is existing
    assert chat_llm.calls == []
    create_docx_mock.assert_not_awaited()
    assert fake_medical_record_repo.mark_ready_calls == []
    assert fake_medical_record_repo.mark_failed_calls == []


@pytest.mark.asyncio
async def test_generate_with_changed_diagnosis_creates_additional_record_without_touching_the_first(
    fake_medical_record_repo, monkeypatch,
):
    """If the appointment's purpose changed since the last generation, a
    fresh call to generate() (diagnosis defaulting to the new purpose) must
    create an independent new record rather than overwriting/returning the
    record for the old diagnosis."""
    appointment = _appointment(purpose="Пульпит 46 зуба")
    client = _client()
    old_diagnosis_record = MedicalRecord(
        id=5, appointment_id=appointment.id, diagnosis="Средний кариес 37 зуба",
        status=MedicalRecordStatus.READY, file_path="/existing/path.docx",
    )
    fake_medical_record_repo.records.append(old_diagnosis_record)

    chat_llm = FakeChatLLM(response=LLM_RESPONSE)
    service = MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment, client), chat_llm, instance="zb",
    )
    create_docx_mock = AsyncMock(return_value="/data/history_of_illness/generated/medical_card_2.docx")
    monkeypatch.setattr(
        "bot.services.medical_record.medical_record_management.create_docx", create_docx_mock,
    )

    result = await service.generate(appointment.id)

    assert result is not None
    assert result.id != old_diagnosis_record.id
    assert result.diagnosis == "Пульпит 46 зуба"
    assert result.status is MedicalRecordStatus.READY
    create_docx_mock.assert_awaited_once()

    untouched = await fake_medical_record_repo.get_by_appointment_and_diagnosis(
        appointment.id, "Средний кариес 37 зуба",
    )
    assert untouched.status is MedicalRecordStatus.READY
    assert untouched.file_path == "/existing/path.docx"


@pytest.mark.asyncio
async def test_generate_on_unchanged_diagnosis_returns_existing_record_without_creating_a_new_one(
    fake_medical_record_repo, monkeypatch,
):
    appointment = _appointment()
    client = _client()
    existing = MedicalRecord(
        id=5, appointment_id=appointment.id, diagnosis=appointment.purpose,
        status=MedicalRecordStatus.READY, file_path="/existing/path.docx",
    )
    fake_medical_record_repo.records.append(existing)

    chat_llm = FakeChatLLM(response=LLM_RESPONSE)
    service = MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment, client), chat_llm, instance="zb",
    )
    create_docx_mock = AsyncMock()
    monkeypatch.setattr(
        "bot.services.medical_record.medical_record_management.create_docx", create_docx_mock,
    )

    result = await service.generate(appointment.id, diagnosis=appointment.purpose)

    assert result is existing
    create_docx_mock.assert_not_awaited()
    assert len(fake_medical_record_repo.records) == 1


@pytest.mark.asyncio
async def test_generate_returns_none_without_creating_a_record_when_appointment_missing(fake_medical_record_repo):
    """When the appointment itself cannot be found, generate() bails out
    before any record is created or touched (there is no appointment.purpose
    to default the diagnosis from, and nothing meaningful to mark failed)."""
    chat_llm = FakeChatLLM(response=LLM_RESPONSE)
    service = MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment=None, client=None), chat_llm, instance="zb",
    )

    result = await service.generate(appointment_id=404)

    assert result is None
    assert fake_medical_record_repo.create_pending_calls == []
    assert fake_medical_record_repo.mark_failed_calls == []


@pytest.mark.asyncio
async def test_generate_marks_failed_when_client_missing(fake_medical_record_repo):
    appointment = _appointment()
    service = MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment, client=None), FakeChatLLM(), instance="zb",
    )

    result = await service.generate(appointment.id)

    assert result is None
    assert fake_medical_record_repo.mark_failed_calls
    failed_record = await fake_medical_record_repo.get_by_appointment_and_diagnosis(
        appointment.id, appointment.purpose,
    )
    assert failed_record.status is MedicalRecordStatus.FAILED
    assert failed_record.error_message == "Клиент не найден."


@pytest.mark.asyncio
async def test_generate_marks_failed_when_instance_has_no_configured_template(fake_medical_record_repo, monkeypatch):
    """"mm" has no MEDICAL_RECORD_TEMPLATE_BY_INSTANCE entry yet -- this is an
    expected "not set up" case (like price_list/location stubs), not a bug:
    generation must not be attempted and no LLM call/docx render should happen."""
    appointment = _appointment()
    client = _client()
    chat_llm = FakeChatLLM(response=LLM_RESPONSE)
    service = MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment, client), chat_llm, instance="mm",
    )

    create_docx_mock = AsyncMock()
    monkeypatch.setattr(
        "bot.services.medical_record.medical_record_management.create_docx", create_docx_mock,
    )

    result = await service.generate(appointment.id)

    assert result is None
    assert chat_llm.calls == []
    create_docx_mock.assert_not_awaited()
    assert fake_medical_record_repo.mark_failed_calls
    failed_record = await fake_medical_record_repo.get_by_appointment_and_diagnosis(appointment.id, appointment.purpose)
    assert failed_record.status is MedicalRecordStatus.FAILED
    assert failed_record.error_message == "Шаблон истории болезни не настроен для этой клиники."


# --- get_ready_documents ---

@pytest.mark.asyncio
async def test_get_ready_documents_returns_only_ready_records_for_the_appointment(fake_medical_record_repo):
    ready = MedicalRecord(
        id=1, appointment_id=1, diagnosis="Кариес 37", status=MedicalRecordStatus.READY,
        file_path="/existing/path.docx",
    )
    pending = MedicalRecord(id=2, appointment_id=1, diagnosis="Консультация", status=MedicalRecordStatus.PENDING)
    fake_medical_record_repo.records.extend([ready, pending])
    service = MedicalRecordService(fake_medical_record_repo, FakeAppointmentManagement(), FakeChatLLM(), instance="zb")

    documents = await service.get_ready_documents(1)

    assert documents == [ready]


# --- mark_for_regeneration ---

@pytest.mark.asyncio
async def test_mark_for_regeneration_resets_the_given_record_id_to_pending(fake_medical_record_repo):
    existing = MedicalRecord(
        id=7, appointment_id=10, diagnosis="Кариес 37", status=MedicalRecordStatus.READY,
        file_path="/existing/path.docx",
    )
    fake_medical_record_repo.records.append(existing)
    service = MedicalRecordService(fake_medical_record_repo, FakeAppointmentManagement(), FakeChatLLM(), instance="zb")

    await service.mark_for_regeneration(existing.id)

    assert [call[0] for call in fake_medical_record_repo.mark_pending_calls] == [7]
    updated = await fake_medical_record_repo.get_by_appointment_and_diagnosis(10, "Кариес 37")
    assert updated.status is MedicalRecordStatus.PENDING
    assert updated.file_path is None


# --- ensure_file_exists ---

@pytest.mark.asyncio
async def test_ensure_file_exists_returns_record_unchanged_when_file_present(
    fake_medical_record_repo, tmp_path,
):
    file_path = tmp_path / "medical_card_1.docx"
    file_path.write_bytes(b"")
    record = MedicalRecord(
        id=1, appointment_id=10, diagnosis="Кариес 37", status=MedicalRecordStatus.READY, file_path=str(file_path),
    )
    service = MedicalRecordService(fake_medical_record_repo, FakeAppointmentManagement(), FakeChatLLM(), instance="zb")

    result = await service.ensure_file_exists(record)

    assert result is record
    assert fake_medical_record_repo.mark_pending_calls == []


@pytest.mark.asyncio
async def test_ensure_file_exists_regenerates_when_file_missing_from_disk(
    fake_medical_record_repo, monkeypatch, tmp_path,
):
    """The appointment's purpose has since changed to "Пульпит 46" -- but
    this record's own diagnosis is "Кариес 37". Regeneration must be keyed
    by the record's own diagnosis, not the appointment's current purpose,
    so it must land back on the SAME record instead of spawning a new one
    for the new purpose."""
    appointment = _appointment(purpose="Пульпит 46")
    client = _client()
    fake_medical_record_repo.records.append(
        MedicalRecord(
            id=1, appointment_id=appointment.id, diagnosis="Кариес 37",
            status=MedicalRecordStatus.READY, file_path=str(tmp_path / "gone.docx"),
        ),
    )
    record = fake_medical_record_repo.records[0]

    regenerated_path = tmp_path / "medical_card_1_v2.docx"

    def _write_file(*args, **kwargs):
        regenerated_path.write_bytes(b"")
        return str(regenerated_path)

    create_docx_mock = AsyncMock(side_effect=_write_file)
    monkeypatch.setattr(
        "bot.services.medical_record.medical_record_management.create_docx", create_docx_mock,
    )

    chat_llm = FakeChatLLM(response=LLM_RESPONSE)
    service = MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment, client), chat_llm, instance="zb",
    )

    result = await service.ensure_file_exists(record)

    assert result is not None
    assert result.id == 1
    assert result.diagnosis == "Кариес 37"
    assert result.status is MedicalRecordStatus.READY
    assert result.file_path == str(regenerated_path)
    assert [call[0] for call in fake_medical_record_repo.mark_pending_calls] == [1]
    # No second record was spawned for the appointment's new purpose.
    assert len(fake_medical_record_repo.records) == 1


@pytest.mark.asyncio
async def test_ensure_file_exists_returns_none_when_regeneration_fails(fake_medical_record_repo, monkeypatch):
    appointment = _appointment()
    client = _client()
    fake_medical_record_repo.records.append(
        MedicalRecord(
            id=1, appointment_id=appointment.id, diagnosis=appointment.purpose,
            status=MedicalRecordStatus.READY, file_path="/does/not/exist.docx",
        ),
    )
    record = fake_medical_record_repo.records[0]

    create_docx_mock = AsyncMock(side_effect=RuntimeError("render failed"))
    monkeypatch.setattr(
        "bot.services.medical_record.medical_record_management.create_docx", create_docx_mock,
    )

    service = MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment, client), FakeChatLLM(response=LLM_RESPONSE),
        instance="zb",
    )

    result = await service.ensure_file_exists(record)

    assert result is None


# --- stale GENERATING regeneration ---

@pytest.mark.asyncio
async def test_generate_regenerates_a_stale_generating_row_instead_of_returning_it_forever(
    fake_medical_record_repo, monkeypatch,
):
    """A GENERATING row abandoned mid-render (e.g. process crashed) must not
    block the button forever -- once its updated_at is older than
    STALE_GENERATING_MINUTES, generate() must treat it as abandoned and
    regenerate."""
    appointment = _appointment()
    client = _client()
    stale_updated_at = get_current_tashkent_datetime() - timedelta(minutes=STALE_GENERATING_MINUTES + 1)
    existing = MedicalRecord(
        id=5, appointment_id=appointment.id, diagnosis=appointment.purpose, status=MedicalRecordStatus.GENERATING,
        file_path=None, updated_at=stale_updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    )
    fake_medical_record_repo.records.append(existing)

    chat_llm = FakeChatLLM(response=LLM_RESPONSE)
    service = MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment, client), chat_llm, instance="zb",
    )
    create_docx_mock = AsyncMock(return_value="/data/history_of_illness/generated/medical_card_5.docx")
    monkeypatch.setattr(
        "bot.services.medical_record.medical_record_management.create_docx", create_docx_mock,
    )

    result = await service.generate(appointment.id)

    assert result.id == existing.id
    assert result.status is MedicalRecordStatus.READY
    create_docx_mock.assert_awaited_once()
    assert len(chat_llm.calls) == 1


@pytest.mark.asyncio
async def test_generate_returns_a_fresh_generating_row_unchanged(fake_medical_record_repo, monkeypatch):
    """A GENERATING row updated within STALE_GENERATING_MINUTES is a normal
    in-flight generation -- must still be returned as-is, not regenerated."""
    appointment = _appointment()
    client = _client()
    fresh_updated_at = get_current_tashkent_datetime() - timedelta(minutes=1)
    existing = MedicalRecord(
        id=5, appointment_id=appointment.id, diagnosis=appointment.purpose, status=MedicalRecordStatus.GENERATING,
        file_path=None, updated_at=fresh_updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    )
    fake_medical_record_repo.records.append(existing)

    chat_llm = FakeChatLLM(response=LLM_RESPONSE)
    service = MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment, client), chat_llm, instance="zb",
    )
    create_docx_mock = AsyncMock()
    monkeypatch.setattr(
        "bot.services.medical_record.medical_record_management.create_docx", create_docx_mock,
    )

    result = await service.generate(appointment.id)

    assert result is existing
    create_docx_mock.assert_not_awaited()
    assert chat_llm.calls == []


# --- diagnosis=None coercion ---

@pytest.mark.asyncio
async def test_generate_coerces_none_diagnosis_to_empty_string_without_crashing(
    fake_medical_record_repo, monkeypatch,
):
    """appointment.purpose (or an explicitly passed diagnosis) being None must
    never reach the DB's NOT NULL diagnosis column / raise a raw
    IntegrityError -- it is coerced to an empty string instead."""
    appointment = _appointment(purpose=None)
    client = _client()
    chat_llm = FakeChatLLM(response=LLM_RESPONSE)
    service = MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment, client), chat_llm, instance="zb",
    )
    create_docx_mock = AsyncMock(return_value="/data/history_of_illness/generated/medical_card_1.docx")
    monkeypatch.setattr(
        "bot.services.medical_record.medical_record_management.create_docx", create_docx_mock,
    )

    result = await service.generate(appointment.id)

    assert result is not None
    assert result.diagnosis == ""
    assert result.status is MedicalRecordStatus.READY
    # The empty-string coercion must happen before the value is handed
    # toward the repository/DB, not just show up on the returned record.
    assert fake_medical_record_repo.create_pending_calls[0][1] == ""


# --- AI-authored fields (diagnosis is sourced from appointment.purpose, not the LLM) ---

@pytest.mark.asyncio
async def test_generate_ai_fields_returns_llm_response_keys_as_is(fake_medical_record_repo):
    """_generate_ai_fields only covers the four AI-authored keys the LLM is
    responsible for; diagnosis is populated separately in generate() from
    appointment.purpose and is never requested from the LLM."""
    chat_llm = FakeChatLLM(response=LLM_RESPONSE)
    service = MedicalRecordService(fake_medical_record_repo, FakeAppointmentManagement(), chat_llm, instance="zb")

    ai_fields, partial = await service._generate_ai_fields("Средний кариес 37 зуба", _client())

    assert partial is False
    assert ai_fields == {
        "complaints": LLM_RESPONSE["complaints"],
        "diseases": LLM_RESPONSE["diseases"],
        "examination": LLM_RESPONSE["examination"],
        "treatment": LLM_RESPONSE["treatment"],
        "tooth_map": LLM_RESPONSE["tooth_map"],
    }


@pytest.mark.asyncio
async def test_generate_ai_fields_returns_empty_strings_and_partial_true_on_llm_failure(fake_medical_record_repo):
    chat_llm = FakeChatLLM(error=MedicalRecordGenerationError("boom"))
    service = MedicalRecordService(fake_medical_record_repo, FakeAppointmentManagement(), chat_llm, instance="zb")

    ai_fields, partial = await service._generate_ai_fields("Консультация", _client())

    assert partial is True
    assert ai_fields == {
        "complaints": "",
        "diseases": "",
        "examination": "",
        "treatment": "",
        "tooth_map": [],
    }


# --- _build_output_path / _sanitize_path_segment ---

@pytest.mark.asyncio
async def test_build_output_path_uses_clinic_doctor_patient_and_diagnosis_segments(fake_medical_record_repo):
    """Patient is not repeated in the filename since it is already the parent
    directory -- the filename itself is date_diagnosis_recordId.docx."""
    appointment = _appointment()
    appointment.clinic_name = "Зуб Мудрости"
    appointment.doctor_full_name = "Петров Пётр"
    client = _client()
    service = MedicalRecordService(fake_medical_record_repo, FakeAppointmentManagement(), FakeChatLLM(), instance="zb")

    path = service._build_output_path(appointment, client, "Средний кариес 37 зуба", record_id=42)

    assert path.parent == OUTPUT_DIR / "Зуб Мудрости" / "Петров Пётр" / client.full_name
    assert path.suffix == ".docx"
    assert "Средний кариес 37 зуба" in path.name
    assert path.name.endswith("_42.docx")


@pytest.mark.asyncio
async def test_build_output_path_falls_back_when_clinic_or_doctor_missing(fake_medical_record_repo):
    appointment = _appointment()
    client = _client()
    service = MedicalRecordService(fake_medical_record_repo, FakeAppointmentManagement(), FakeChatLLM(), instance="zb")

    path = service._build_output_path(appointment, client, "Консультация", record_id=1)

    assert path.parent == OUTPUT_DIR / "Клиника" / "Без_врача" / client.full_name


@pytest.mark.asyncio
async def test_build_output_path_caps_all_segments_including_clinic_and_doctor(fake_medical_record_repo):
    """Every path segment (clinic/doctor/patient/diagnosis) is capped at
    PATH_SEGMENT_MAX_LENGTH -- not just the diagnosis -- to stay well under
    Windows' MAX_PATH."""
    appointment = _appointment()
    appointment.clinic_name = "К" * (PATH_SEGMENT_MAX_LENGTH + 20)
    appointment.doctor_full_name = "Д" * (PATH_SEGMENT_MAX_LENGTH + 20)
    client = _client()
    client.full_name = "П" * (PATH_SEGMENT_MAX_LENGTH + 20)
    service = MedicalRecordService(fake_medical_record_repo, FakeAppointmentManagement(), FakeChatLLM(), instance="zb")

    path = service._build_output_path(appointment, client, "Консультация", record_id=1)

    clinic_segment, doctor_segment, patient_segment = path.parts[-4:-1]
    assert len(clinic_segment) <= PATH_SEGMENT_MAX_LENGTH
    assert len(doctor_segment) <= PATH_SEGMENT_MAX_LENGTH
    assert len(patient_segment) <= PATH_SEGMENT_MAX_LENGTH


def test_sanitize_path_segment_replaces_unsafe_filesystem_characters():
    from bot.services.medical_record.medical_record_management import _sanitize_path_segment

    assert _sanitize_path_segment(r'a:b/c\d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"


def test_sanitize_path_segment_strips_trailing_dots_and_spaces():
    from bot.services.medical_record.medical_record_management import _sanitize_path_segment

    assert _sanitize_path_segment("Иванов Иван. ") == "Иванов Иван"


def test_sanitize_path_segment_guards_windows_reserved_names():
    from bot.services.medical_record.medical_record_management import _sanitize_path_segment

    assert _sanitize_path_segment("CON") == "CON_"
    assert _sanitize_path_segment("com3") == "com3_"


def test_sanitize_path_segment_falls_back_to_underscore_for_empty_result():
    from bot.services.medical_record.medical_record_management import _sanitize_path_segment

    assert _sanitize_path_segment("   ...   ") == "_"


def test_sanitize_path_segment_truncates_to_max_length():
    from bot.services.medical_record.medical_record_management import _sanitize_path_segment

    long_diagnosis = "К" * (DIAGNOSIS_SEGMENT_MAX_LENGTH + 20)

    sanitized = _sanitize_path_segment(long_diagnosis, max_length=DIAGNOSIS_SEGMENT_MAX_LENGTH)

    assert len(sanitized) <= DIAGNOSIS_SEGMENT_MAX_LENGTH
