"""Tests for appointment_card_kb's status-aware branching logic.

The keyboard is driven by an editing matrix (see refactoring_record_update.md):

| Status                  | Service | Status | Price | Time | Delete | Status menu |
|--------------------------|:-------:|:------:|:-----:|:----:|:------:|:------------:|
| PENDING                  |    Y    |   Y    |   N   |  Y   |   Y    |      N       |
| CONFIRMED                |    Y    |   Y    |   N   |  Y   |   Y    |      N       |
| POST_APPOINTMENT_EDIT    |    Y    |   Y*   |   Y   |  N   |   N    |      -       |
| COMPLETED                |    Y    |   N    |   Y   |  N   |   N    |      Y       |
| CANCELLED                |    N    |   N    |   N   |  N   |   N    |      Y       |
| EXPIRED                  |    N    |   N    |   N   |  N   |   N    |      N       |
| NO_SHOW                  |    N    |   N    |   N   |  N   |   N    |      Y       |

* post-appointment status change offers all 3 terminal statuses (CANCELLED/
  NO_SHOW/COMPLETED) via "select_status" (a pure re-render, never a
  repository write), plus a dedicated "finish_appointment" action that
  commits whichever of the 3 is currently selected.

Buttons are never disabled - unavailable actions are simply not added to the
keyboard.
"""

from bot.keyboards.admin.record_management_kb.appointment_browser_cb import (
    ApptActionCB,
    ApptCardCB,
    ApptPageCB,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_kb import (
    appointment_card_kb,
    appointment_status_menu_kb,
)
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


def _select_status_cb(appointment_id, mode, page, status_value, post_appt=True):
    return ApptActionCB(
        action="select_status", appointment_id=appointment_id, mode=mode, page=page, value=status_value,
        post_appt=post_appt,
    ).pack()


def _finish_cb(appointment_id, mode, page, status_value, post_appt=True):
    return ApptActionCB(
        action="finish_appointment", appointment_id=appointment_id, mode=mode, page=page, value=status_value,
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


def test_completed_shows_service_and_price_and_status_menu_no_status_no_time():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.COMPLETED, tab="completed")
    callback_datas = _callback_datas(markup)

    for status_value in ("confirmed", "cancelled", "completed", "no_show"):
        assert _status_cb(1, "list", 1, status_value) not in callback_datas

    assert _action_cb("edit_purpose", 1, "list", 1) in callback_datas
    assert _action_cb("edit_price", 1, "list", 1) in callback_datas
    assert _action_cb("edit_datetime", 1, "list", 1) not in callback_datas
    assert _action_cb("delete", 1, "list", 1) not in callback_datas
    assert _action_cb("status_menu", 1, "list", 1) in callback_datas
    assert _back_cb("list", 1, "completed") in callback_datas


def test_cancelled_shows_status_menu_and_back_button_only():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.CANCELLED, tab="cancelled")
    callback_datas = _callback_datas(markup)

    assert callback_datas == [
        _action_cb("status_menu", 1, "list", 1),
        _back_cb("list", 1, "cancelled"),
    ]


def test_expired_shows_only_back_button():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.EXPIRED, tab="expired")
    callback_datas = _callback_datas(markup)

    assert callback_datas == [_back_cb("list", 1, "expired")]


def test_no_show_shows_status_menu_and_back_button_only():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.NO_SHOW, tab="no_show")
    callback_datas = _callback_datas(markup)

    assert callback_datas == [
        _action_cb("status_menu", 1, "list", 1),
        _back_cb("list", 1, "no_show"),
    ]


def test_status_menu_button_shown_only_for_completed_no_show_cancelled():
    for status in AppointmentStatus:
        markup = appointment_card_kb(1, "list", 1, status=status)
        callback_datas = _callback_datas(markup)
        is_present = _action_cb("status_menu", 1, "list", 1) in callback_datas
        expected = status in (
            AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW, AppointmentStatus.CANCELLED,
        )
        assert is_present == expected, f"status_menu button presence mismatch for status={status}"


def test_delete_action_present_only_for_pending_and_confirmed():
    for status in AppointmentStatus:
        markup = appointment_card_kb(1, "list", 1, status=status)
        callback_datas = _callback_datas(markup)
        is_present = _action_cb("delete", 1, "list", 1) in callback_datas
        expected = status in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)
        assert is_present == expected, f"delete button presence mismatch for status={status}"


def test_post_appt_shows_three_status_buttons_via_select_status_action():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.CONFIRMED, post_appt=True)
    callback_datas = _callback_datas(markup)

    for status_value in ("cancelled", "no_show", "completed"):
        assert _select_status_cb(1, "list", 1, status_value) in callback_datas

    # None of the 3 post-appt status buttons use the plain "set_status" action
    # anymore -- that would commit immediately instead of just re-rendering.
    for status_value in ("cancelled", "no_show", "completed"):
        assert _status_cb(1, "list", 1, status_value, post_appt=True) not in callback_datas


def test_post_appt_shows_service_and_price_but_not_time():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.CONFIRMED, post_appt=True)
    callback_datas = _callback_datas(markup)

    assert _action_cb("edit_purpose", 1, "list", 1, post_appt=True) in callback_datas
    assert _action_cb("edit_price", 1, "list", 1, post_appt=True) in callback_datas
    assert _action_cb("edit_datetime", 1, "list", 1, post_appt=True) not in callback_datas


def test_post_appt_shows_finish_appointment_button_carrying_effective_selected_value():
    markup = appointment_card_kb(
        1, "list", 1, status=AppointmentStatus.CONFIRMED, post_appt=True,
        selected_status=AppointmentStatus.CANCELLED,
    )
    callback_datas = _callback_datas(markup)

    assert _finish_cb(1, "list", 1, "cancelled") in callback_datas


def test_post_appt_finish_button_defaults_value_to_current_status_when_no_selection():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.COMPLETED, post_appt=True)
    callback_datas = _callback_datas(markup)

    assert _finish_cb(1, "list", 1, "completed") in callback_datas


def test_post_appt_marks_explicitly_selected_status_with_checkbox():
    markup = appointment_card_kb(
        1, "list", 1, status=AppointmentStatus.CONFIRMED, post_appt=True,
        selected_status=AppointmentStatus.NO_SHOW,
    )
    buttons = _all_buttons(markup)

    marked = [b for b in buttons if b.text.startswith("☑️")]
    assert len(marked) == 1
    assert ApptActionCB.unpack(marked[0].callback_data).value == "no_show"


def test_post_appt_marks_current_status_when_no_explicit_selection_and_status_matches_a_button():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.COMPLETED, post_appt=True)
    buttons = _all_buttons(markup)

    marked = [b for b in buttons if b.text.startswith("☑️")]
    assert len(marked) == 1
    assert ApptActionCB.unpack(marked[0].callback_data).value == "completed"


def test_post_appt_marks_nothing_when_current_status_is_not_a_terminal_status():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.CONFIRMED, post_appt=True)
    buttons = _all_buttons(markup)

    assert not any(b.text.startswith("☑️") for b in buttons)


def test_post_appt_omits_back_to_list_button():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.CONFIRMED, tab="confirmed", post_appt=True)
    callback_datas = _callback_datas(markup)

    assert _back_cb("list", 1, "confirmed") not in callback_datas
    assert not any(cb.startswith("appt_page") for cb in callback_datas)


def test_post_appt_row_layout():
    markup = appointment_card_kb(1, "list", 1, status=AppointmentStatus.CONFIRMED, post_appt=True)

    assert [len(row) for row in markup.inline_keyboard] == [3, 2, 1]


def test_status_menu_kb_excludes_current_status_and_includes_other_two():
    markup = appointment_status_menu_kb(
        1, "list", 1, tab="completed", status=AppointmentStatus.COMPLETED,
    )
    callback_datas = _callback_datas(markup)

    assert _status_cb(1, "list", 1, "cancelled") in callback_datas
    assert _status_cb(1, "list", 1, "no_show") in callback_datas
    assert _status_cb(1, "list", 1, "completed") not in callback_datas


def test_status_menu_kb_includes_back_button_to_the_card():
    markup = appointment_status_menu_kb(
        1, "list", 1, tab="completed", status=AppointmentStatus.COMPLETED,
    )
    callback_datas = _callback_datas(markup)

    assert ApptCardCB(appointment_id=1, mode="list", page=1, tab="completed").pack() in callback_datas


def test_status_menu_kb_row_layout():
    markup = appointment_status_menu_kb(1, "list", 1, tab="", status=AppointmentStatus.COMPLETED)

    assert [len(row) for row in markup.inline_keyboard] == [2, 1]
