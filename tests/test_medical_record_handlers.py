"""Tests for the "get_medical_record" button-press action wired into both the
admin appointment_browser router and the client appointment_response router.

Both handlers share the same shape: resolve ownership first (deny access to
appointments that do not belong to this admin/client), then delegate to
deliver_medical_record (already covered in isolation by
test_medical_record_delivery.py) for the ready/pending/fallback branches.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.admin.appointment_management.appointment_browser import (
    create_admin_appointment_browser_router,
)
from bot.handlers.client.appointment_response import create_client_appointment_router
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import ApptActionCB
from bot.keyboards.client.appointment_history_cb import ClientHistoryActionCB
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.medical_record import MedicalRecord
from bot.models.staff import Staff
from bot.models.user import User
from bot.services.appointment.appointment_pagination_service import AppointmentPaginationService
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.medical_record_enums import MedicalRecordStatus
from bot.utils.role import Role


ADMIN_TELEGRAM_ID = 999
OTHER_ADMIN_TELEGRAM_ID = 1000
CLIENT_TELEGRAM_ID = 555
OTHER_CLIENT_TELEGRAM_ID = 556


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _callback_query(telegram_user_id):
    callback_query = MagicMock()
    callback_query.from_user.id = telegram_user_id
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    callback_query.message.answer_document = AsyncMock()
    return callback_query


def _medical_record_service(record, needs_generation=False):
    service = MagicMock()
    service.get_or_generate = AsyncMock(return_value=(record, needs_generation))
    return service


def _appointment_scheduler():
    scheduler = MagicMock()
    scheduler.schedule_medical_record_generation = AsyncMock()
    return scheduler


READY_RECORD = MedicalRecord(
    id=1, appointment_id=1, status=MedicalRecordStatus.READY, file_path="/data/medical_card_1.docx",
)
PENDING_RECORD = MedicalRecord(id=1, appointment_id=1, status=MedicalRecordStatus.PENDING, file_path=None)


# --- Admin side (appointment_browser.py) ---

class FakeAdminAppointmentRepository:
    def __init__(self, appointment):
        self.appointment = appointment

    async def get_appointment_by_id(self, appointment_id):
        return self.appointment

    async def get_appointments_by_doctor_and_date(self, doctor_id, date):
        return []


class FakeAdminUserRepo:
    def __init__(self, admin):
        self.admin = admin

    async def get_user_by_telegram_id(self, telegram_user_id):
        if self.admin.telegram_user_id == telegram_user_id:
            return self.admin
        return None


class FakeAdminStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=1, visibility_scope="clinic")


class FakeAdminClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=1, name="Зуб Мудрости", token="t")


def _admin(clinic_id=1):
    return User(
        full_name="Петров Петр",
        phone="+998907654321",
        role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID,
        ID=1,
        clinic_id=clinic_id,
        clinic_name="Зуб Мудрости",
    )


def _admin_appointment(clinic_id=1, status=AppointmentStatus.COMPLETED):
    return Appointment(
        clinic_id=clinic_id,
        client_id=7,
        datetime="2026-07-10 14:30",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=status,
        id=1,
    )


def _admin_router(appointment, admin, medical_record_service, appointment_scheduler):
    return create_admin_appointment_browser_router(
        FakeAdminAppointmentRepository(appointment),
        FakeAdminUserRepo(admin),
        FakeAdminStaffRepo(),
        FakeAdminClinicRepo(),
        appointment_scheduler=appointment_scheduler,
        medical_record_service=medical_record_service,
    )


@pytest.mark.asyncio
async def test_admin_get_medical_record_ready_sends_document():
    router = _admin_router(
        _admin_appointment(), _admin(), _medical_record_service(READY_RECORD), _appointment_scheduler(),
    )
    handler = _find_handler(router, "get_medical_record")
    callback_query = _callback_query(ADMIN_TELEGRAM_ID)
    callback_data = ApptActionCB(action="get_medical_record", appointment_id=1, mode="list", page=1)

    await handler(callback_query, callback_data, AsyncMock())

    callback_query.message.answer_document.assert_awaited_once()
    sent_document = callback_query.message.answer_document.call_args.args[0]
    assert sent_document.path == "/data/medical_card_1.docx"


@pytest.mark.asyncio
async def test_admin_get_medical_record_pending_shows_alert_without_document():
    scheduler = _appointment_scheduler()
    router = _admin_router(
        _admin_appointment(), _admin(), _medical_record_service(PENDING_RECORD), scheduler,
    )
    handler = _find_handler(router, "get_medical_record")
    callback_query = _callback_query(ADMIN_TELEGRAM_ID)
    callback_data = ApptActionCB(action="get_medical_record", appointment_id=1, mode="list", page=1)

    await handler(callback_query, callback_data, AsyncMock())

    callback_query.message.answer_document.assert_not_awaited()
    callback_query.answer.assert_awaited_once_with(
        "Документ ещё готовится, попробуйте через пару минут", show_alert=True,
    )
    scheduler.schedule_medical_record_generation.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_get_medical_record_no_prior_record_triggers_fallback_generation():
    scheduler = _appointment_scheduler()
    service = _medical_record_service(PENDING_RECORD, needs_generation=True)
    router = _admin_router(_admin_appointment(), _admin(), service, scheduler)
    handler = _find_handler(router, "get_medical_record")
    callback_query = _callback_query(ADMIN_TELEGRAM_ID)
    callback_data = ApptActionCB(action="get_medical_record", appointment_id=1, mode="list", page=1)

    await handler(callback_query, callback_data, AsyncMock())

    scheduler.schedule_medical_record_generation.assert_awaited_once_with(1)
    callback_query.message.answer_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_get_medical_record_denies_access_to_other_clinic_appointment():
    """Ownership check: an admin from a different clinic must not be able to
    trigger/receive a medical record for an appointment outside their scope --
    deliver_medical_record must never even be reached."""
    service = _medical_record_service(READY_RECORD)
    scheduler = _appointment_scheduler()
    router = _admin_router(_admin_appointment(clinic_id=2), _admin(clinic_id=1), service, scheduler)
    handler = _find_handler(router, "get_medical_record")
    callback_query = _callback_query(ADMIN_TELEGRAM_ID)
    callback_data = ApptActionCB(action="get_medical_record", appointment_id=1, mode="list", page=1)

    await handler(callback_query, callback_data, AsyncMock())

    callback_query.answer.assert_awaited_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.answer_document.assert_not_awaited()
    service.get_or_generate.assert_not_awaited()
    scheduler.schedule_medical_record_generation.assert_not_awaited()


# --- Client side (appointment_response.py) ---

class FakeClientAppointmentManagementService:
    def __init__(self, appointment, client):
        self.appointment = appointment
        self.client = client
        self.get_appointment_for_client_calls: list[tuple[int, int]] = []

    async def get_appointment_for_client(self, appointment_id, telegram_user_id):
        self.get_appointment_for_client_calls.append((appointment_id, telegram_user_id))
        if self.appointment is None or self.appointment.id != appointment_id:
            return None
        if self.client is None or self.client.telegram_user_id != telegram_user_id:
            return None
        if self.appointment.client_id != self.client.ID:
            return None
        return self.appointment


def _client_user(telegram_user_id=CLIENT_TELEGRAM_ID, client_id=7):
    return User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=telegram_user_id,
        ID=client_id,
    )


def _client_appointment(client_id=7, status=AppointmentStatus.COMPLETED):
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        datetime="2026-07-10 14:30",
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=status,
        id=1,
    )


def _client_router(appointment, client, medical_record_service, appointment_scheduler):
    appointment_management_service = FakeClientAppointmentManagementService(appointment, client)
    notification_service = MagicMock()
    return create_client_appointment_router(
        AppointmentPaginationService(MagicMock()),
        appointment_management_service,
        notification_service,
        appointment_scheduler,
        medical_record_service,
    ), appointment_management_service


@pytest.mark.asyncio
async def test_client_get_medical_record_ready_sends_document():
    router, _ = _client_router(
        _client_appointment(), _client_user(), _medical_record_service(READY_RECORD), _appointment_scheduler(),
    )
    handler = _find_handler(router, "history_action")
    callback_query = _callback_query(CLIENT_TELEGRAM_ID)
    callback_data = ClientHistoryActionCB(action="get_medical_record", appointment_id=1, tab="completed", page=1)

    await handler(callback_query, callback_data, AsyncMock())

    callback_query.message.answer_document.assert_awaited_once()
    sent_document = callback_query.message.answer_document.call_args.args[0]
    assert sent_document.path == "/data/medical_card_1.docx"


@pytest.mark.asyncio
async def test_client_get_medical_record_pending_shows_alert_without_document():
    scheduler = _appointment_scheduler()
    router, _ = _client_router(
        _client_appointment(), _client_user(), _medical_record_service(PENDING_RECORD), scheduler,
    )
    handler = _find_handler(router, "history_action")
    callback_query = _callback_query(CLIENT_TELEGRAM_ID)
    callback_data = ClientHistoryActionCB(action="get_medical_record", appointment_id=1, tab="completed", page=1)

    await handler(callback_query, callback_data, AsyncMock())

    callback_query.message.answer_document.assert_not_awaited()
    callback_query.answer.assert_awaited_once_with(
        "Документ ещё готовится, попробуйте через пару минут", show_alert=True,
    )
    scheduler.schedule_medical_record_generation.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_get_medical_record_no_prior_record_triggers_fallback_generation():
    scheduler = _appointment_scheduler()
    service = _medical_record_service(PENDING_RECORD, needs_generation=True)
    router, _ = _client_router(_client_appointment(), _client_user(), service, scheduler)
    handler = _find_handler(router, "history_action")
    callback_query = _callback_query(CLIENT_TELEGRAM_ID)
    callback_data = ClientHistoryActionCB(action="get_medical_record", appointment_id=1, tab="completed", page=1)

    await handler(callback_query, callback_data, AsyncMock())

    scheduler.schedule_medical_record_generation.assert_awaited_once_with(1)
    callback_query.message.answer_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_get_medical_record_denies_access_to_other_clients_appointment():
    """Ownership check: a client must not be able to fetch another client
    appointment history document -- deliver_medical_record must never be
    reached when get_appointment_for_client returns None."""
    service = _medical_record_service(READY_RECORD)
    scheduler = _appointment_scheduler()
    router, appointment_management_service = _client_router(
        _client_appointment(client_id=7), _client_user(telegram_user_id=OTHER_CLIENT_TELEGRAM_ID, client_id=8),
        service, scheduler,
    )
    handler = _find_handler(router, "history_action")
    callback_query = _callback_query(OTHER_CLIENT_TELEGRAM_ID)
    callback_data = ClientHistoryActionCB(action="get_medical_record", appointment_id=1, tab="completed", page=1)

    await handler(callback_query, callback_data, AsyncMock())

    callback_query.answer.assert_awaited_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.answer_document.assert_not_awaited()
    service.get_or_generate.assert_not_awaited()
    scheduler.schedule_medical_record_generation.assert_not_awaited()
    assert appointment_management_service.get_appointment_for_client_calls == [(1, OTHER_CLIENT_TELEGRAM_ID)]


@pytest.mark.asyncio
async def test_client_get_medical_record_answers_unavailable_when_service_not_configured():
    """When medical_record_service/appointment_scheduler were not injected
    (feature not wired up for this deployment), the handler must answer with
    a graceful "unavailable" alert instead of raising."""
    router, appointment_management_service = _client_router(
        _client_appointment(), _client_user(), None, None,
    )
    handler = _find_handler(router, "history_action")
    callback_query = _callback_query(CLIENT_TELEGRAM_ID)
    callback_data = ClientHistoryActionCB(action="get_medical_record", appointment_id=1, tab="completed", page=1)

    await handler(callback_query, callback_data, AsyncMock())

    callback_query.answer.assert_awaited_once_with("Функция недоступна.", show_alert=True)
    callback_query.message.answer_document.assert_not_awaited()
    assert appointment_management_service.get_appointment_for_client_calls == []
