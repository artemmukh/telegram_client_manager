"""Focused router contracts for administrative document management."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers.admin.appointment_management.medical_documents import (
    create_admin_medical_documents_router,
)
from bot.keyboards.admin.record_management_kb.medical_documents_cb import (
    MedicalDocumentActionCB,
    MedicalDocumentAppointmentCB,
    MedicalDocumentListCB,
)
from bot.models.appointment import Appointment
from bot.models.medical_record import MedicalRecord
from bot.models.user import User
from bot.states.admin.record_management.medical_documents_states import (
    MedicalDocumentStates,
)
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.medical_record_enums import MedicalRecordStatus
from bot.utils.role import Role

ADMIN_TELEGRAM_ID = 991


def _find_callback_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"callback handler {name} not found")


def _find_message_handler(router, name):
    for handler in router.message.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"message handler {name} not found")


def _callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    callback_query.message.answer = AsyncMock()
    callback_query.message.answer_document = AsyncMock()
    callback_query.message.chat.id = 1
    callback_query.message.message_id = 2
    return callback_query


def _message(text: str):
    message = MagicMock()
    message.text = text
    message.from_user.id = ADMIN_TELEGRAM_ID
    message.answer = AsyncMock()
    message.answer_document = AsyncMock()
    message.bot.edit_message_text = AsyncMock()
    return message


def _state(data=None):
    state = MagicMock()
    state.get_data = AsyncMock(return_value=data or {"card_chat_id": 1, "card_message_id": 2})
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    return state


def _admin():
    return User(
        full_name="Администратор",
        phone="+998901111111",
        role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID,
        ID=3,
        clinic_id=1,
    )


def _appointment(status=AppointmentStatus.COMPLETED):
    return Appointment(
        clinic_id=1,
        client_id=5,
        datetime="2026-09-07 10:00:00",
        purpose="Старая услуга",
        created_by=CreatedBy.ADMIN,
        status=status,
        id=1,
    )


def _document(status=MedicalRecordStatus.READY):
    return MedicalRecord(
        id=7,
        appointment_id=1,
        diagnosis="Кариес 37",
        status=status,
        file_path="C:/safe/record.docx",
    )


def _router(appointment=None, document=None):
    appointment_management = MagicMock()
    appointment_management.get_appointment_for_admin = AsyncMock(return_value=appointment or _appointment())
    appointment_management.resolve_admin_appointment_filter = AsyncMock(return_value=(1, None))
    client_management = MagicMock()
    client_management.get_client_by_id = AsyncMock(return_value=User(
        full_name="Клиент", phone="+998902222222", role=Role.CLIENT, ID=5, clinic_id=1,
    ))
    medical_record_service = MagicMock()
    medical_record_service.get_document_by_id = AsyncMock(return_value=document or _document())
    medical_record_service.delete_document = AsyncMock(return_value=True)
    medical_record_service.generate = AsyncMock(return_value=document or _document())
    medical_record_service.ensure_file_exists = AsyncMock(return_value=document or _document())
    medical_record_service.paginate_appointment_documents = AsyncMock(
        return_value=SimpleNamespace(items=[], current_page=1, total_pages=1),
    )
    medical_record_service.paginate_client_documents = AsyncMock(
        return_value=SimpleNamespace(items=[], current_page=1, total_pages=1),
    )
    return (
        create_admin_medical_documents_router(
            medical_record_service, appointment_management, client_management,
        ),
        medical_record_service,
        appointment_management,
    )


@pytest.mark.asyncio
async def test_download_rechecks_appointment_scope_before_selected_delivery():
    router, service, _ = _router()
    handler = _find_callback_handler(router, "download_document")
    callback_query = _callback_query()
    callback_data = MedicalDocumentActionCB(
        action="download", source="a", source_id=1, record_id=7,
    )

    with patch(
        "bot.handlers.admin.appointment_management.medical_documents.deliver_selected_medical_record",
        new=AsyncMock(),
    ) as deliver:
        await handler(callback_query, callback_data, _admin())

    service.get_document_by_id.assert_awaited_once_with(7)
    deliver.assert_awaited_once_with(callback_query, service, 7, 1, lang="ru")


@pytest.mark.asyncio
async def test_client_document_download_rejects_a_document_of_another_client():
    router, service, _ = _router()
    handler = _find_callback_handler(router, "download_document")
    callback_query = _callback_query()
    callback_data = MedicalDocumentActionCB(
        action="download", source="c", source_id=999, record_id=7,
    )

    with patch(
        "bot.handlers.admin.appointment_management.medical_documents.deliver_selected_medical_record",
        new=AsyncMock(),
    ) as deliver:
        await handler(callback_query, callback_data, _admin())

    service.get_document_by_id.assert_awaited_once_with(7)
    deliver.assert_not_awaited()
    callback_query.answer.assert_awaited_once_with("Документ или запись больше недоступны.", show_alert=True)


@pytest.mark.asyncio
async def test_client_document_download_allows_historical_document_after_status_change():
    router, service, _ = _router(appointment=_appointment(AppointmentStatus.CANCELLED))
    handler = _find_callback_handler(router, "download_document")
    callback_query = _callback_query()
    callback_data = MedicalDocumentActionCB(
        action="download", source="c", source_id=5, record_id=7,
    )

    with patch(
        "bot.handlers.admin.appointment_management.medical_documents.deliver_selected_medical_record",
        new=AsyncMock(),
    ) as deliver:
        await handler(callback_query, callback_data, _admin())

    deliver.assert_awaited_once_with(callback_query, service, 7, 1, lang="ru")


@pytest.mark.asyncio
async def test_non_ready_document_download_returns_status_without_delivery():
    router, _service, _ = _router(document=_document(MedicalRecordStatus.GENERATING))
    handler = _find_callback_handler(router, "download_document")
    callback_query = _callback_query()
    callback_data = MedicalDocumentActionCB(
        action="download", source="a", source_id=1, record_id=7,
    )

    with patch(
        "bot.handlers.admin.appointment_management.medical_documents.deliver_selected_medical_record",
        new=AsyncMock(),
    ) as deliver:
        await handler(callback_query, callback_data, _admin())

    deliver.assert_not_awaited()
    callback_query.answer.assert_awaited_once_with("Документ ещё не готов к скачиванию.", show_alert=True)


@pytest.mark.asyncio
async def test_opening_another_document_list_clears_pending_temporary_diagnosis():
    router, service, _ = _router()
    handler = _find_callback_handler(router, "paginate_documents")
    callback_query = _callback_query()
    storage = MemoryStorage()
    state = FSMContext(storage, StorageKey(bot_id=1, chat_id=1, user_id=ADMIN_TELEGRAM_ID))
    await state.set_state(MedicalDocumentStates.diagnosis)
    await state.update_data(
        document_generation_appointment_id=1,
        document_page=1,
        card_chat_id=1,
        card_message_id=2,
    )
    callback_data = MedicalDocumentListCB(source="a", source_id=2, page=1)

    try:
        await handler(callback_query, callback_data, state, _admin())

        assert await state.get_state() is None
        assert (await state.get_data())["document_generation_appointment_id"] is None
    finally:
        await storage.close()
    service.paginate_appointment_documents.assert_awaited_once_with(2, 1)


@pytest.mark.asyncio
async def test_bulk_delivery_rechecks_completed_appointment_and_never_uses_legacy_helper():
    router, service, _ = _router()
    handler = _find_callback_handler(router, "deliver_all_documents")
    callback_query = _callback_query()
    callback_data = MedicalDocumentAppointmentCB(action="b", appointment_id=1)

    with patch(
        "bot.handlers.admin.appointment_management.medical_documents.deliver_ready_medical_records",
        new=AsyncMock(),
    ) as deliver:
        await handler(callback_query, callback_data, _admin())

    deliver.assert_awaited_once_with(callback_query, service, 1, lang="ru")


@pytest.mark.asyncio
async def test_cancel_temporary_diagnosis_returns_to_the_current_document_page():
    router, service, _ = _router()
    handler = _find_callback_handler(router, "cancel_document_generation")
    callback_query = _callback_query()
    state = _state({"document_page": 2, "card_chat_id": 1, "card_message_id": 2})
    callback_data = MedicalDocumentAppointmentCB(action="c", appointment_id=1)

    await handler(callback_query, callback_data, state, _admin())

    state.set_state.assert_awaited_once_with(None)
    service.paginate_appointment_documents.assert_awaited_once_with(1, 2)


@pytest.mark.asyncio
async def test_delete_only_calls_service_after_explicit_confirmation():
    router, service, _ = _router()
    request_handler = _find_callback_handler(router, "request_delete_document")
    confirm_handler = _find_callback_handler(router, "confirm_delete_document")
    callback_query = _callback_query()
    state = _state()
    request = MedicalDocumentActionCB(
        action="delete", source="a", source_id=1, record_id=7,
    )
    confirm = MedicalDocumentActionCB(
        action="confirm_delete", source="a", source_id=1, record_id=7,
    )

    await request_handler(callback_query, request, state, _admin())
    service.delete_document.assert_not_awaited()

    await confirm_handler(callback_query, confirm, state, _admin())
    service.delete_document.assert_awaited_once_with(7, 1)


@pytest.mark.asyncio
async def test_temporary_diagnosis_generates_without_mutating_appointment_purpose():
    router, service, appointment_management = _router()
    handler = _find_message_handler(router, "generate_document_from_diagnosis")
    message = _message("Кариес 37")
    state = _state({
        "document_generation_appointment_id": 1,
        "document_page": 1,
        "card_chat_id": 1,
        "card_message_id": 2,
    })

    await handler(message, state, _admin())

    service.generate.assert_awaited_once_with(1, "Кариес 37")
    assert _appointment().purpose == "Старая услуга"
    assert all(call[0] != "update_purpose" for call in appointment_management.mock_calls)
    message.answer_document.assert_awaited_once()
