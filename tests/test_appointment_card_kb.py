"""Tests for appointment_card_kb's status-aware branching logic.

appointment_card_kb hides the one status-action button matching the
appointment's current status (re-applying the same status is meaningless).
PENDING and EXPIRED have no matching button, so all 4 status buttons stay
visible for those.
"""

from bot.keyboards.admin.record_management_kb.appointment_browser_cb import ApptActionCB, ApptPageCB
from bot.keyboards.admin.record_management_kb.appointment_browser_kb import appointment_card_kb
from bot.utils.appointment_enums import AppointmentStatus

_ALL_STATUS_VALUES = {
    AppointmentStatus.CONFIRMED.value,
    AppointmentStatus.CANCELLED.value,
    AppointmentStatus.COMPLETED.value,
    AppointmentStatus.NO_SHOW.value,
}


def _all_buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def _status_action_callback_data(appointment_id, mode, page, status_value):
    return ApptActionCB(
        action="set_status", appointment_id=appointment_id, mode=mode, page=page, value=status_value,
    ).pack()


def _fixed_action_callback_datas(appointment_id, mode, page, tab):
    return {
        "edit_datetime": ApptActionCB(action="edit_datetime", appointment_id=appointment_id, mode=mode, page=page).pack(),
        "edit_purpose": ApptActionCB(action="edit_purpose", appointment_id=appointment_id, mode=mode, page=page).pack(),
        "delete": ApptActionCB(action="delete", appointment_id=appointment_id, mode=mode, page=page).pack(),
        "back": ApptPageCB(mode=mode, page=page, tab=tab).pack(),
    }


def _assert_fixed_actions_present(callback_datas, appointment_id, mode, page, tab):
    fixed = _fixed_action_callback_datas(appointment_id, mode, page, tab)
    for cb in fixed.values():
        assert cb in callback_datas


def test_appointment_card_kb_pending_shows_all_four_status_buttons():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.PENDING, tab="pending")

    callback_datas = [button.callback_data for button in _all_buttons(markup)]

    for status_value in _ALL_STATUS_VALUES:
        assert _status_action_callback_data(1, "list", 1, status_value) in callback_datas

    _assert_fixed_actions_present(callback_datas, 1, "list", 1, "pending")
    assert markup.inline_keyboard[0] and len(markup.inline_keyboard[0]) == 2
    assert len(markup.inline_keyboard[1]) == 2
    assert [len(row) for row in markup.inline_keyboard] == [2, 2, 2, 1, 1]


def test_appointment_card_kb_expired_shows_all_four_status_buttons():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.EXPIRED, tab="expired")

    callback_datas = [button.callback_data for button in _all_buttons(markup)]

    for status_value in _ALL_STATUS_VALUES:
        assert _status_action_callback_data(1, "list", 1, status_value) in callback_datas

    _assert_fixed_actions_present(callback_datas, 1, "list", 1, "expired")
    assert [len(row) for row in markup.inline_keyboard] == [2, 2, 2, 1, 1]


def _assert_only_matching_status_hidden(status: AppointmentStatus, tab: str):
    markup = appointment_card_kb(1, "list", 1, status=status, tab=tab)

    callback_datas = [button.callback_data for button in _all_buttons(markup)]

    hidden_value = status.value
    expected_present = _ALL_STATUS_VALUES - {hidden_value}

    for status_value in expected_present:
        assert _status_action_callback_data(1, "list", 1, status_value) in callback_datas

    assert _status_action_callback_data(1, "list", 1, hidden_value) not in callback_datas

    _assert_fixed_actions_present(callback_datas, 1, "list", 1, tab)
    assert [len(row) for row in markup.inline_keyboard] == [2, 1, 2, 1, 1]


def test_appointment_card_kb_confirmed_hides_confirm_button():
    _assert_only_matching_status_hidden(AppointmentStatus.CONFIRMED, "confirmed")


def test_appointment_card_kb_cancelled_hides_cancel_button():
    _assert_only_matching_status_hidden(AppointmentStatus.CANCELLED, "cancelled")


def test_appointment_card_kb_completed_hides_completed_button():
    _assert_only_matching_status_hidden(AppointmentStatus.COMPLETED, "completed")


def test_appointment_card_kb_no_show_hides_no_show_button():
    _assert_only_matching_status_hidden(AppointmentStatus.NO_SHOW, "no_show")
