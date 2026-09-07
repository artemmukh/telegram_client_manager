"""TDD coverage for the administrative medical-document keyboard contract."""

from bot.keyboards.admin.record_management_kb.medical_documents_cb import (
    MedicalDocumentActionCB,
    MedicalDocumentAppointmentCB,
    MedicalDocumentListCB,
    MedicalDocumentRecordCB,
)
from bot.keyboards.admin.record_management_kb.medical_documents_kb import (
    medical_document_detail_kb,
    medical_document_generation_cancel_kb,
    medical_documents_list_kb,
)
from bot.models.medical_record import MedicalRecord
from bot.utils.medical_record_enums import MedicalRecordStatus


def _callback_data(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_document_callback_payloads_round_trip_within_telegram_limit():
    callbacks = [
        MedicalDocumentListCB(source="a", source_id=123456, page=12),
        MedicalDocumentRecordCB(source="c", source_id=123456, record_id=999999),
        MedicalDocumentActionCB(action="delete", source="a", source_id=123456, record_id=999999),
    ]

    for callback in callbacks:
        packed = callback.pack()
        assert len(packed.encode()) <= 64
        assert type(callback).unpack(packed) == callback

    max_integer = 9_223_372_036_854_775_807
    assert len(MedicalDocumentActionCB(
        action="confirm_delete", source="c", source_id=max_integer, record_id=max_integer,
    ).pack().encode()) <= 64


def test_appointment_documents_list_has_records_generation_bulk_and_back():
    document = MedicalRecord(
        id=7,
        appointment_id=11,
        diagnosis="Кариес 37",
        status=MedicalRecordStatus.READY,
        created_at="2026-09-07 10:00:00",
    )

    markup = medical_documents_list_kb(
        [document],
        source="a",
        source_id=11,
        page=1,
        total_pages=1,
        back_callback_data="appt_card:11:list:2:completed:0",
        lang="ru",
    )
    callback_data = _callback_data(markup)

    record_callback = MedicalDocumentRecordCB.unpack(callback_data[0])
    assert record_callback.record_id == 7
    assert "2026-09-07 10:00:00" in markup.inline_keyboard[0][0].text
    assert "Готов" in markup.inline_keyboard[0][0].text
    assert any(data.startswith("mdp:g:") for data in callback_data)
    assert any(data.startswith("mdp:b:") for data in callback_data)
    assert "appt_card:11:list:2:completed:0" in callback_data


def test_client_documents_list_has_no_generation_or_bulk_and_keeps_document_context():
    document = MedicalRecord(
        id=7,
        appointment_id=11,
        diagnosis="Кариес 37",
        status=MedicalRecordStatus.READY_PARTIAL,
        appointment_datetime="2026-09-06 09:30:00",
        doctor_full_name="Доктор Тест",
        created_at="2026-09-07 11:30:00",
    )

    markup = medical_documents_list_kb(
        [document],
        source="c",
        source_id=22,
        page=2,
        total_pages=3,
        back_callback_data="cl_card:22:search:4",
        lang="ru",
    )
    callback_data = _callback_data(markup)

    record_callback = MedicalDocumentRecordCB.unpack(callback_data[0])
    assert record_callback.source == "c"
    assert record_callback.source_id == 22
    assert "2026-09-07 11:30:00" in markup.inline_keyboard[0][0].text
    assert "2026-09-06 09:30:00" in markup.inline_keyboard[0][0].text
    assert "Доктор Тест" in markup.inline_keyboard[0][0].text
    assert not any(data.startswith("mdp:") for data in callback_data)
    assert "cl_card:22:search:4" in callback_data


def test_document_detail_has_download_delete_and_back():
    markup = medical_document_detail_kb(
        source="a",
        source_id=11,
        record_id=7,
        page=2,
        status=MedicalRecordStatus.READY,
        lang="ru",
    )
    callbacks = [MedicalDocumentActionCB.unpack(data) for data in _callback_data(markup) if data.startswith("mda:")]

    assert {callback.action for callback in callbacks} == {"download", "delete"}
    assert any(data.startswith("mdl:a:11:2") for data in _callback_data(markup))


def test_temporary_diagnosis_prompt_has_a_cancellation_callback():
    markup = medical_document_generation_cancel_kb(11, lang="ru")
    callback = MedicalDocumentAppointmentCB.unpack(_callback_data(markup)[0])

    assert callback.action == "c"
    assert callback.appointment_id == 11


def test_non_ready_document_detail_hides_download_and_keeps_delete():
    markup = medical_document_detail_kb(
        source="a",
        source_id=11,
        record_id=7,
        page=1,
        status=MedicalRecordStatus.GENERATING,
        lang="ru",
    )
    callbacks = [
        MedicalDocumentActionCB.unpack(data)
        for data in _callback_data(markup)
        if data.startswith("mda:")
    ]

    assert [callback.action for callback in callbacks] == ["delete"]
