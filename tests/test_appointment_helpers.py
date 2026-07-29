from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

import bot.handlers.utils.admin_utils.appointment_helpers as appointment_helpers_module
from bot.handlers.utils.admin_utils.appointment_helpers import build_appointment_card, datetime_processing
from bot.models.appointment import Appointment
from bot.services.utils.date_parser import RESCHEDULE_NEGOTIATION_NOTE
from bot.states.admin.record_management.appointment_states import AppointmentCreationStates
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy


def _appointment(**overrides) -> Appointment:
    fields = dict(
        clinic_id=1,
        client_id=7,
        datetime="2026-07-16 14:30:00",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        id=1,
    )
    fields.update(overrides)
    return Appointment(**fields)


def test_build_appointment_card_shows_formatted_time():
    card = build_appointment_card(_appointment())

    assert "Время: 16.07.2026 14:30" in card


def test_build_appointment_card_formats_time_without_seconds():
    card = build_appointment_card(_appointment(datetime="2026-07-16 14:30"))

    assert "Время: 16.07.2026 14:30" in card


def test_build_appointment_card_omits_doctor_lines_when_doctor_full_name_absent():
    card = build_appointment_card(_appointment())

    assert "Врач:" not in card
    assert "Телефон врача:" not in card


def test_build_appointment_card_shows_doctor_name_and_phone_when_present():
    card = build_appointment_card(
        _appointment(doctor_full_name="Петров Петр", doctor_phone="+998907654321", doctor_is_doctor=True)
    )

    assert "Врач: Петров Петр" in card
    assert "Телефон врача: +998907654321" in card


def test_build_appointment_card_shows_dash_for_doctor_phone_when_missing():
    card = build_appointment_card(_appointment(doctor_full_name="Петров Петр", doctor_is_doctor=True))

    assert "Врач: Петров Петр" in card
    assert "Телефон врача: —" in card


def test_build_appointment_card_omits_doctor_lines_when_not_flagged_as_doctor():
    card = build_appointment_card(
        _appointment(doctor_full_name="Петров Петр", doctor_phone="+998907654321", doctor_is_doctor=False)
    )

    assert "Врач:" not in card
    assert "Телефон врача:" not in card


def test_build_appointment_card_shows_proposal_line_and_note_when_negotiating():
    card = build_appointment_card(
        _appointment(
            status=AppointmentStatus.CONFIRMED,
            proposed_datetime="2026-08-15T15:00:00",
            proposed_by=CreatedBy.CLIENT,
        )
    )

    assert "Клиент предложил перенос на: 15 августа 2026, 15:00" in card
    assert RESCHEDULE_NEGOTIATION_NOTE in card


def test_build_appointment_card_shows_own_proposal_when_admin_proposed():
    card = build_appointment_card(
        _appointment(
            status=AppointmentStatus.CONFIRMED,
            proposed_datetime="2026-08-15T15:00:00",
            proposed_by=CreatedBy.ADMIN,
        )
    )

    assert "Вы предложили перенос на: 15 августа 2026, 15:00" in card
    assert RESCHEDULE_NEGOTIATION_NOTE in card


def test_build_appointment_card_omits_proposal_line_and_note_when_no_proposal():
    card = build_appointment_card(_appointment(status=AppointmentStatus.CONFIRMED))

    assert "предложил" not in card
    assert RESCHEDULE_NEGOTIATION_NOTE not in card


def _message(text):
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    return message


@pytest.fixture
def fsm_context():
    return FSMContext(storage=MemoryStorage(), key=(1, 1))


@pytest.mark.asyncio
async def test_datetime_processing_stores_confirmation_display_string_on_success(fsm_context, monkeypatch):
    parsed_dt = datetime(2026, 7, 30, 16, 0)
    monkeypatch.setattr(appointment_helpers_module, "parse_ru_datetime", lambda text: parsed_dt)

    message = _message("30.07 16:00")

    result = await datetime_processing(message, fsm_context, AppointmentCreationStates.appointment_datetime_confirm)

    assert result is True
    data = await fsm_context.get_data()
    assert data["appointment_datetime_parsed"] == parsed_dt
    assert data["appointment_datetime_display"] == "четверг, 30 июля 2026, 16:00"
    assert await fsm_context.get_state() == AppointmentCreationStates.appointment_datetime_confirm


@pytest.mark.asyncio
async def test_datetime_processing_returns_false_and_reprompts_on_unparseable_input(fsm_context, monkeypatch):
    monkeypatch.setattr(appointment_helpers_module, "parse_ru_datetime", lambda text: None)

    message = _message("абракадабра")

    result = await datetime_processing(message, fsm_context, AppointmentCreationStates.appointment_datetime_confirm)

    assert result is False
    message.answer.assert_awaited_once()
    assert await fsm_context.get_data() == {}
    assert await fsm_context.get_state() is None


@pytest.mark.asyncio
async def test_datetime_processing_logs_raw_text_on_parse_failure(fsm_context, monkeypatch, caplog):
    monkeypatch.setattr(appointment_helpers_module, "parse_ru_datetime", lambda text: None)

    message = _message("  абракадабра  ")

    with caplog.at_level("INFO", logger=appointment_helpers_module.logger.name):
        await datetime_processing(message, fsm_context, AppointmentCreationStates.appointment_datetime_confirm)

    assert "абракадабра" in caplog.text
    assert "Failed to parse" in caplog.text


@pytest.mark.asyncio
async def test_datetime_processing_logs_raw_text_and_parsed_result_on_success(fsm_context, monkeypatch, caplog):
    parsed_dt = datetime(2026, 7, 30, 16, 0)
    monkeypatch.setattr(appointment_helpers_module, "parse_ru_datetime", lambda text: parsed_dt)

    message = _message("30.07 16:00")

    with caplog.at_level("INFO", logger=appointment_helpers_module.logger.name):
        await datetime_processing(message, fsm_context, AppointmentCreationStates.appointment_datetime_confirm)

    assert "30.07 16:00" in caplog.text
    assert str(parsed_dt) in caplog.text
