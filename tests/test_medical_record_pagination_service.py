"""RED coverage for scoped medical-record pagination APIs.

The repository fake deliberately records every scope and page argument so a
pagination service cannot accidentally fetch an unscoped page or return the
requested out-of-range page as if it were valid.
"""

import pytest

from bot.models.medical_record import MedicalRecord
from bot.services.medical_record.medical_record_management import MedicalRecordService
from bot.utils.medical_record_enums import MedicalRecordStatus
from tests.conftest import FakeAppointmentManagement, FakeChatLLM


def _record(record_id: int, appointment_id: int, created_at: str) -> MedicalRecord:
    return MedicalRecord(
        id=record_id,
        appointment_id=appointment_id,
        diagnosis=f"Диагноз {record_id}",
        status=MedicalRecordStatus.READY,
        file_path=f"/tmp/{record_id}.docx",
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_appointment_document_page_clamps_page_and_forwards_scope(
    fake_medical_record_repo,
):
    fake_medical_record_repo.records.extend(
        _record(record_id, 10, f"2026-09-{record_id:02d} 10:00:00")
        for record_id in range(1, 26)
    )
    service = MedicalRecordService(
        fake_medical_record_repo,
        FakeAppointmentManagement(),
        FakeChatLLM(),
        instance="zb",
    )

    result = await service.paginate_appointment_documents(appointment_id=10, page=999)

    assert result.current_page == 3
    assert result.total_pages == 3
    assert result.total_count == 25
    assert [item.id for item in result.items] == [5, 4, 3, 2, 1]
    assert fake_medical_record_repo.count_by_appointment_id_calls == [10]
    assert fake_medical_record_repo.list_by_appointment_id_calls == [(10, 10, 20)]


@pytest.mark.asyncio
async def test_client_document_page_forwards_client_clinic_doctor_scope_and_clamps_low_page(
    fake_medical_record_repo,
):
    records = []
    for record_id in range(1, 13):
        record = _record(record_id, 100 + record_id, f"2026-09-{record_id:02d} 10:00:00")
        record.client_id = 7
        record.clinic_id = 3
        record.doctor_id = 42
        records.append(record)
    foreign = _record(99, 199, "2026-09-30 10:00:00")
    foreign.client_id = 8
    foreign.clinic_id = 3
    foreign.doctor_id = 42
    records.append(foreign)
    fake_medical_record_repo.records.extend(records)

    service = MedicalRecordService(
        fake_medical_record_repo,
        FakeAppointmentManagement(),
        FakeChatLLM(),
        instance="zb",
    )

    result = await service.paginate_client_documents(
        client_id=7,
        clinic_id=3,
        doctor_id=42,
        page=0,
    )

    assert result.current_page == 1
    assert result.total_pages == 2
    assert result.total_count == 12
    assert [item.id for item in result.items] == list(range(12, 2, -1))
    assert fake_medical_record_repo.count_by_client_id_calls == [(7, 3, 42)]
    assert fake_medical_record_repo.list_by_client_id_calls == [(7, 3, 42, 10, 0)]
