"""Tests for appointment_card_kb's status-aware branching logic.

The keyboard is driven by an editing matrix (see refactoring_record_update.md):

| Status                  | Service | Status | Price | Time | Delete |
|--------------------------|:-------:|:------:|:-----:|:----:|:------:|
| PENDING                  |    Y    |   Y    |   N   |  Y   |   Y    |
| CONFIRMED                |    Y    |   Y    |   N   |  Y   |   Y    |
| POST_APPOINTMENT_EDIT    |    Y    |   Y*   |   Y   |  N   |   N    |
| COMPLETED                |    Y    |   N    |   Y   |  N   |   N    |
| CANCELLED                |    N    |   N    |   N   |  N   |   N    |
| EXPIRED                  |    N    |   N    |   N   |  N   |   N    |
| NO_SHOW                  |    N    |   N    |   N   |  N   |   N    |

* post-appointment status change is limited to CANCELLED/NO_SHOW only, plus a
  dedicated "finish_appointment" action (never a set_status button).

Buttons are never disabled - unavailable actions are simply not added to the
keyboard.
"""

from bot.keyboards.admin.record_management_kb.appointment_browser_cb import ApptActionCB, ApptPageCB
from bot.keyboards.admin.record_management_kb.appointment_browser_kb import appointment_card_kb
from bot.utils.appointment_enums import AppointmentStatus


def _all_buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def _callback_datas(markup):
    return [button.callback_data for button in _all_buttons(markup)]


def _status_cb(appointment_id, mode, page, status_value, post_appt=False):
    return ApptActionCB(
        action="set_status", appointment_id=appointment_id, mode=mode, page=page, value=status_value,
        post_appt=post_appt,
    ).pack()


def _action_cb(action, appointment_id, mode, page, post_appt=False):
    return ApptActionCB(
        action=action, appointment_id=appointment_id, mode=mode, page=page, post_appt=post_appt,
    ).pack()


def _back_cb(mode, page, tab):
    return ApptPageCB(mode=mode, page=page, tab=tab).pack()


def test_pending_shows_two_status_buttons_and_service_and_time():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.PENDING, tab="pending")
    callback_datas = _callback_datas(markup)

    for status_value in ("confirmed", "cancelled"):
        assert _status_cb(1, "list", 1, status_value) in callback_datas

    assert _status_cb(1, "list", 1, "completed") not in callback_datas
    assert _status_cb(1, "list", 1, "no_show") not in callback_datas

    assert _action_cb("edit_purpose", 1, "list", 1) in callback_datas
    assert _action_cb("edit_datetime", 1, "list", 1) in callback_datas
    assert _action_cb("edit_price", 1, "list", 1) not in callback_datas
    assert _back_cb("list", 1, "pending") in callback_datas
    assert _action_cb("delete", 1, "list", 1) in callback_datas
    assert _action_cb("finish_appointment", 1, "list", 1) not in callback_datas


def test_confirmed_hides_confirm_button_but_keeps_other_three():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.CONFIRMED, tab="confirmed")
    callback_datas = _callback_datas(markup)

    assert _status_cb(1, "list", 1, "confirmed") not in callback_datas
    for status_value in ("cancelled", "completed", "no_show"):
        assert _status_cb(1, "list", 1, status_value) in callback_datas

    assert _action_cb("edit_purpose", 1, "list", 1) in callback_datas
    assert _action_cb("edit_datetime", 1, "list", 1) in callback_datas
    assert _action_cb("edit_price", 1, "list", 1) not in callback_datas
    assert _action_cb("delete", 1, "list", 1) in callback_datas
    assert _back_cb("list", 1, "confirmed") in callback_datas


def test_completed_shows_only_service_and_price_no_status_no_time():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.COMPLETED, tab="completed")
    callback_datas = _callback_datas(markup)

    for status_value in ("confirmed", "cancelled", "completed", "no_show"):
        assert _status_cb(1, "list", 1, status_value) not in callback_datas

    assert _action_cb("edit_purpose", 1, "list", 1) in callback_datas
    assert _action_cb("edit_price", 1, "list", 1) in callback_datas
    assert _action_cb("edit_datetime", 1, "list", 1) not in callback_datas
    assert _action_cb("delete", 1, "list", 1) not in callback_datas
    assert _back_cb("list", 1, "completed") in callback_datas


def test_cancelled_shows_only_back_button():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.CANCELLED, tab="cancelled")
    callback_datas = _callback_datas(markup)

    assert callback_datas == [_back_cb("list", 1, "cancelled")]


def test_expired_shows_only_back_button():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.EXPIRED, tab="expired")
    callback_datas = _callback_datas(markup)

    assert callback_datas == [_back_cb("list", 1, "expired")]


def test_no_show_shows_only_back_button():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.NO_SHOW, tab="no_show")
    callback_datas = _callback_datas(markup)

    assert callback_datas == [_back_cb("list", 1, "no_show")]


def test_delete_action_present_only_for_pending_and_confirmed():
    for status in AppointmentStatus:
        markup = appointment_card_kb(1, "list", 1, status=status)
        callback_datas = _callback_datas(markup)
        is_present = _action_cb("delete", 1, "list", 1) in callback_datas
        expected = status in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)
        assert is_present == expected, f"delete button presence mismatch for status={status}"


def test_post_appt_shows_only_cancelled_and_no_show_status_buttons():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.CONFIRMED, post_appt=True)
    callback_datas = _callback_datas(markup)

    assert _status_cb(1, "list", 1, "cancelled", post_appt=True) in callback_datas
    assert _status_cb(1, "list", 1, "no_show", post_appt=True) in callback_datas
    assert _status_cb(1, "list", 1, "confirmed", post_appt=True) not in callback_datas
    assert _status_cb(1, "list", 1, "completed", post_appt=True) not in callback_datas


def test_post_appt_shows_service_and_price_but_not_time():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.CONFIRMED, post_appt=True)
    callback_datas = _callback_datas(markup)

    assert _action_cb("edit_purpose", 1, "list", 1, post_appt=True) in callback_datas
    assert _action_cb("edit_price", 1, "list", 1, post_appt=True) in callback_datas
    assert _action_cb("edit_datetime", 1, "list", 1, post_appt=True) not in callback_datas


def test_post_appt_shows_finish_appointment_button():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.CONFIRMED, post_appt=True)
    callback_datas = _callback_datas(markup)

    assert _action_cb("finish_appointment", 1, "list", 1, post_appt=True) in callback_datas


def test_post_appt_omits_back_to_list_button():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.CONFIRMED, tab="confirmed", post_appt=True)
    callback_datas = _callback_datas(markup)

    assert _back_cb("list", 1, "confirmed") not in callback_datas
    assert not any(cb.startswith("appt_page") for cb in callback_datas)


def test_post_appt_row_layout():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.CONFIRMED, post_appt=True)

    assert [len(row) for row in markup.inline_keyboard] == [2, 2, 1]
