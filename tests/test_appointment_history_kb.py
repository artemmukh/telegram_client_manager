"""Tests for appointment_history_card_kb's action-button wiring.

appointment_history_card_kb receives can_cancel/can_reschedule flags computed
by the caller (business/time logic lives in the handler, not the keyboard) and
builds the corresponding buttons via the shared _add_status_action_buttons
helper (also used by appointment_manage_card_kb).
"""

from bot.keyboards.client.appointment_history_cb import ClientHistoryActionCB, ClientHistoryPageCB
from bot.keyboards.client.appointment_history_kb import appointment_history_card_kb
from bot.keyboards.client.reschedule_cb import ClientRescheduleStartCB
from bot.models.appointment import Appointment
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy


def _appointment(**overrides):
    fields = dict(
        clinic_id=1,
        client_id=1,
        datetime="2026-07-10 14:30",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.CONFIRMED,
        id=1,
        clinic_name="Зуб Мудрости",
    )
    fields.update(overrides)
    return Appointment(**fields)


def _all_buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def test_appointment_history_card_kb_shows_cancel_and_reschedule_when_both_allowed():
    appointment = _appointment()

    markup = appointment_history_card_kb(appointment, tab="confirmed", page=1, can_cancel=True, can_reschedule=True)

    buttons = _all_buttons(markup)
    callback_datas = [button.callback_data for button in buttons]

    assert callback_datas == [
        ClientHistoryActionCB(action="cancel_ask", appointment_id=1, tab="confirmed", page=1).pack(),
        ClientRescheduleStartCB(appointment_id=1).pack(),
        ClientHistoryPageCB(tab="confirmed", page=1).pack(),
    ]


def test_appointment_history_card_kb_hides_both_buttons_when_not_allowed():
    appointment = _appointment(status=AppointmentStatus.CANCELLED)

    markup = appointment_history_card_kb(appointment, tab="cancelled", page=2, can_cancel=False, can_reschedule=False)

    buttons = _all_buttons(markup)
    callback_datas = [button.callback_data for button in buttons]

    assert callback_datas == [
        ClientHistoryPageCB(tab="cancelled", page=2).pack(),
    ]


def test_appointment_history_card_kb_shows_only_cancel_when_reschedule_not_allowed():
    appointment = _appointment()

    markup = appointment_history_card_kb(appointment, tab="confirmed", page=1, can_cancel=True, can_reschedule=False)

    buttons = _all_buttons(markup)
    callback_datas = [button.callback_data for button in buttons]

    assert callback_datas == [
        ClientHistoryActionCB(action="cancel_ask", appointment_id=1, tab="confirmed", page=1).pack(),
        ClientHistoryPageCB(tab="confirmed", page=1).pack(),
    ]
