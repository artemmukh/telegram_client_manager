"""Tests for completion_followup_kb's button/callback wiring.

Mirrors the pure-function keyboard-builder testing style used in
tests/test_appointment_manage_kb.py.
"""

from bot.keyboards.admin.record_management_kb.completion_followup_cb import CompletionFollowupCB
from bot.keyboards.admin.record_management_kb.completion_followup_kb import completion_followup_kb


def _all_buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def test_completion_followup_kb_has_yes_and_no_buttons_with_correct_callback_data():
    markup = completion_followup_kb(appointment_id=42)

    buttons = _all_buttons(markup)
    callback_datas = [button.callback_data for button in buttons]

    assert callback_datas == [
        CompletionFollowupCB(action="edit", appointment_id=42).pack(),
        CompletionFollowupCB(action="skip", appointment_id=42).pack(),
    ]


def test_completion_followup_kb_uses_appointment_id_for_both_buttons():
    markup = completion_followup_kb(appointment_id=7)

    buttons = _all_buttons(markup)

    for button in buttons:
        callback_data = CompletionFollowupCB.unpack(button.callback_data)
        assert callback_data.appointment_id == 7

    actions = {CompletionFollowupCB.unpack(b.callback_data).action for b in buttons}
    assert actions == {"edit", "skip"}
