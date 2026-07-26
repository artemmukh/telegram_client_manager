"""Tests for MedicalRecordService.generate()/get_or_generate() and the
JSON-key -> template-placeholder mapping.

create_docx is monkeypatched rather than actually rendering a .docx (no
existing precedent in this repo for testing document-producing code end to
end -- other services stub the rendering step and assert on the data handed
to it, e.g. how price_list/geolocation tests stub FSInputFile rather than
touching the real files).
"""

from unittest.mock import AsyncMock

import pytest

from bot.exceptions.medical_record_exceptions import MedicalRecordGenerationError
from bot.models.appointment import Appointment
from bot.models.medical_record import MedicalRecord
from bot.models.user import User
from bot.services.medical_record.medical_record_management import MedicalRecordService
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.medical_record_enums import MedicalRecordStatus
from bot.utils.role import Role


class FakeAppointmentManagement:
    """Only the two methods MedicalRecordService actually calls
    (get_appointment_by_id/get_client_by_id) -- matching the real
    AppointmentManagement method names/signatures for those two."""

    def __init__(self, appointment=None, client=None):
        self.appointment = appointment
        self.client = client

    async def get_appointment_by_id(self, appointment_id):
        if self.appointment is not None and self.appointment.id == appointment_id:
            return self.appointment
        return None

    async def get_client_by_id(self, user_id):
        if self.client is not None and self.client.ID == user_id:
            return self.client
        return None


class FakeChatLLM:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[str] = []

    async def generate(self, prompt: str) -> dict:
        self.calls.append(prompt)
        if self.error is not None:
            raise self.error
        return dict(self.response)


LLM_RESPONSE = {
    "complaints": "Боль при накусывании",
    "diseases": "Хронический гастрит",
    "examination": "Кариозная полость на жевательной поверхности",
    "treatment": "Пломбирование композитным материалом",
    "tooth_map": [{"tooth": 37, "marker": "C"}],
}


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
    assert len(chat_llm.calls) == 1

    create_docx_mock.assert_awaited_once()
    data_arg, tooth_map_arg, appointment_id_arg, template_path_arg = create_docx_mock.call_args.args
    assert tooth_map_arg == LLM_RESPONSE["tooth_map"]
    assert appointment_id_arg == appointment.id
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
        id=5, appointment_id=appointment.id, status=status, file_path="/existing/path.docx",
    )
    fake_medical_record_repo.records_by_appointment_id[appointment.id] = existing

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
async def test_generate_marks_failed_when_appointment_missing(fake_medical_record_repo):
    chat_llm = FakeChatLLM(response=LLM_RESPONSE)
    service = MedicalRecordService(
        fake_medical_record_repo, FakeAppointmentManagement(appointment=None, client=None), chat_llm, instance="zb",
    )

    result = await service.generate(appointment_id=404)

    assert result is None
    assert fake_medical_record_repo.mark_failed_calls
    failed_record = await fake_medical_record_repo.get_by_appointment_id(404)
    assert failed_record.status is MedicalRecordStatus.FAILED


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
    failed_record = await fake_medical_record_repo.get_by_appointment_id(appointment.id)
    assert failed_record.status is MedicalRecordStatus.FAILED
    assert failed_record.error_message == "Шаблон истории болезни не настроен для этой клиники."


# --- get_or_generate ---

@pytest.mark.asyncio
async def test_get_or_generate_returns_existing_ready_record_without_generation_flag(fake_medical_record_repo):
    existing = MedicalRecord(
        id=1, appointment_id=1, status=MedicalRecordStatus.READY, file_path="/existing/path.docx",
    )
    fake_medical_record_repo.records_by_appointment_id[1] = existing
    service = MedicalRecordService(fake_medical_record_repo, FakeAppointmentManagement(), FakeChatLLM(), instance="zb")

    record, needs_generation = await service.get_or_generate(1)

    assert record is existing
    assert needs_generation is False


@pytest.mark.asyncio
async def test_get_or_generate_creates_pending_row_and_signals_generation_when_no_record_exists(
    fake_medical_record_repo,
):
    service = MedicalRecordService(fake_medical_record_repo, FakeAppointmentManagement(), FakeChatLLM(), instance="zb")

    record, needs_generation = await service.get_or_generate(99)

    assert record.appointment_id == 99
    assert record.status is MedicalRecordStatus.PENDING
    assert needs_generation is True
    assert fake_medical_record_repo.create_pending_calls == [99]


# --- mark_for_regeneration ---

@pytest.mark.asyncio
async def test_mark_for_regeneration_resets_existing_record_to_pending(fake_medical_record_repo):
    existing = MedicalRecord(
        id=1, appointment_id=10, status=MedicalRecordStatus.READY, file_path="/existing/path.docx",
    )
    fake_medical_record_repo.records_by_appointment_id[10] = existing
    service = MedicalRecordService(fake_medical_record_repo, FakeAppointmentManagement(), FakeChatLLM(), instance="zb")

    await service.mark_for_regeneration(10)

    assert fake_medical_record_repo.mark_pending_calls == [1]
    updated = await fake_medical_record_repo.get_by_appointment_id(10)
    assert updated.status is MedicalRecordStatus.PENDING
    assert updated.file_path is None


@pytest.mark.asyncio
async def test_mark_for_regeneration_is_noop_when_no_record_exists(fake_medical_record_repo):
    service = MedicalRecordService(fake_medical_record_repo, FakeAppointmentManagement(), FakeChatLLM(), instance="zb")

    await service.mark_for_regeneration(999)

    assert fake_medical_record_repo.mark_pending_calls == []


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
