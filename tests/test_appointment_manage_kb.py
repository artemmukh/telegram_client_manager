"""Tests for appointment_manage_card_kb's branching logic.

appointment_manage_card_kb builds a different set of action buttons depending on
the appointment's proposal state (proposed_datetime / proposed_by) and status.
This is pure-function branching logic, not Telegram wiring, so it is covered
here the same way bot/handlers/utils/*_helpers.py builders are covered
elsewhere in this project.
"""

from bot.keyboards.client.appointment_manage_cb import ClientManageActionCB, ClientManagePageCB
from bot.keyboards.client.appointment_manage_kb import appointment_manage_card_kb
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


def test_appointment_manage_card_kb_admin_proposed_shows_accept_reject_only():
    appointment = _appointment(proposed_datetime="2026-08-15 15:00", proposed_by=CreatedBy.ADMIN)

    markup = appointment_manage_card_kb(appointment, page=1)

    buttons = _all_buttons(markup)
    callback_datas = [button.callback_data for button in buttons]

    assert callback_datas == [
        ClientManageActionCB(action="accept_proposal", appointment_id=1, page=1).pack(),
        ClientManageActionCB(action="reject_proposal", appointment_id=1, page=1).pack(),
        ClientManagePageCB(page=1).pack(),
    ]
    assert not any(
        cb.startswith(ClientRescheduleStartCB.__prefix__) for cb in callback_datas
    )


def test_appointment_manage_card_kb_client_proposed_shows_cancel_only():
    appointment = _appointment(proposed_datetime="2026-08-15 15:00", proposed_by=CreatedBy.CLIENT)

    markup = appointment_manage_card_kb(appointment, page=2)

    buttons = _all_buttons(markup)
    callback_datas = [button.callback_data for button in buttons]

    assert callback_datas == [
        ClientManageActionCB(action="cancel_ask", appointment_id=1, page=2).pack(),
        ClientManagePageCB(page=2).pack(),
    ]
    assert not any(
        cb.startswith(ClientManageActionCB.__prefix__) and ":confirm:" in cb
        for cb in callback_datas
    )
    assert not any(
        cb.startswith(ClientRescheduleStartCB.__prefix__) for cb in callback_datas
    )


def test_appointment_manage_card_kb_normal_confirmed_shows_reschedule_button():
    appointment = _appointment(status=AppointmentStatus.CONFIRMED)

    markup = appointment_manage_card_kb(appointment, page=1)

    buttons = _all_buttons(markup)
    callback_datas = [button.callback_data for button in buttons]

    assert callback_datas == [
        ClientManageActionCB(action="cancel_ask", appointment_id=1, page=1).pack(),
        ClientRescheduleStartCB(appointment_id=1).pack(),
        ClientManagePageCB(page=1).pack(),
    ]
    assert not any(
        cb.startswith(ClientManageActionCB.__prefix__) and ":confirm:" in cb
        for cb in callback_datas
    )


def test_appointment_manage_card_kb_normal_pending_hides_reschedule_button():
    appointment = _appointment(status=AppointmentStatus.PENDING)

    markup = appointment_manage_card_kb(appointment, page=1)

    buttons = _all_buttons(markup)
    callback_datas = [button.callback_data for button in buttons]

    assert callback_datas == [
        ClientManageActionCB(action="cancel_ask", appointment_id=1, page=1).pack(),
        ClientManagePageCB(page=1).pack(),
    ]
    assert not any(
        cb.startswith(ClientManageActionCB.__prefix__) and ":confirm:" in cb
        for cb in callback_datas
    )
    assert not any(
        cb.startswith(ClientRescheduleStartCB.__prefix__) for cb in callback_datas
    )
