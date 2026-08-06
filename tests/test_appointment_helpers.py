from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

import bot.handlers.utils.admin_utils.appointment_helpers as appointment_helpers_module
import bot.messages.booking as booking_msg
from bot.handlers.utils.admin_utils.appointment_helpers import (
    answer_no_slots_for_day,
    build_appointment_card,
    datetime_processing,
)
from bot.models.appointment import Appointment
from bot.services.utils.date_parser import reschedule_negotiation_note
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
    assert reschedule_negotiation_note("ru") in card


def test_build_appointment_card_shows_own_proposal_when_admin_proposed():
    card = build_appointment_card(
        _appointment(
            status=AppointmentStatus.CONFIRMED,
            proposed_datetime="2026-08-15T15:00:00",
            proposed_by=CreatedBy.ADMIN,
        )
    )

    assert "Вы предложили перенос на: 15 августа 2026, 15:00" in card
    assert reschedule_negotiation_note("ru") in card


def test_build_appointment_card_omits_proposal_line_and_note_when_no_proposal():
    card = build_appointment_card(_appointment(status=AppointmentStatus.CONFIRMED))

    assert "предложил" not in card
    assert reschedule_negotiation_note("ru") not in card


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


# --- answer_no_slots_for_day (admin thin wrapper over the shared helper) ---

def _no_slots_callback_query():
    callback_query = MagicMock()
    callback_query.answer = AsyncMock()
    return callback_query


def _no_slots_state(staff_user_id=42):
    state = MagicMock()
    state.get_data = AsyncMock(return_value={"staff_user_id": staff_user_id})
    return state


@pytest.mark.asyncio
async def test_admin_answer_no_slots_for_day_shows_generic_admin_wording_without_a_block():
    appt_mng = MagicMock()
    appt_mng.get_day_block_reason = AsyncMock(return_value=None)
    callback_query = _no_slots_callback_query()
    state = _no_slots_state(staff_user_id=42)

    await answer_no_slots_for_day(
        appt_mng, callback_query, state, "2026-07-20", datetime(2026, 7, 1, 9, 0), lang="ru",
    )

    appt_mng.get_day_block_reason.assert_awaited_once()
    doctor_id_arg, day_arg, now_arg = appt_mng.get_day_block_reason.await_args.args
    assert doctor_id_arg == 42
    assert day_arg.isoformat() == "2026-07-20"
    assert now_arg == datetime(2026, 7, 1, 9, 0)
    callback_query.answer.assert_awaited_once_with(
        appointment_helpers_module._NO_SLOTS_FOR_DAY["ru"], show_alert=True,
    )


@pytest.mark.asyncio
async def test_admin_answer_no_slots_for_day_shows_block_reason_when_day_is_blocked():
    appt_mng = MagicMock()
    appt_mng.get_day_block_reason = AsyncMock(return_value="Отпуск врача")
    callback_query = _no_slots_callback_query()
    state = _no_slots_state(staff_user_id=42)

    await answer_no_slots_for_day(
        appt_mng, callback_query, state, "2026-07-20", datetime(2026, 7, 1, 9, 0), lang="ru",
    )

    toast_text = callback_query.answer.call_args.args[0]
    assert "Отпуск врача" in toast_text
    assert toast_text != appointment_helpers_module._NO_SLOTS_FOR_DAY["ru"]


def test_admin_and_client_no_slots_wording_are_deliberately_different():
    """These were never unified -- a future refactor must not merge them into
    one shared string, since admin ("no slots for this day") and client
    ("no MORE slots for this day") copy differ on purpose."""
    assert appointment_helpers_module._NO_SLOTS_FOR_DAY["ru"] != booking_msg.no_slots_for_day("ru")
    assert appointment_helpers_module._NO_SLOTS_FOR_DAY["uz"] != booking_msg.no_slots_for_day("uz")
