"""Tests for the new profile/registration/name-change keyboards.

Covers profile_menu_kb's two buttons, reg_name_conflict_kb's Да/Нет buttons,
and name_change_approval_kb's approve/reject buttons (callback data round-trip).
"""

from bot.keyboards.admin.name_change_cb import NameChangeApprovalCB
from bot.keyboards.admin.name_change_kb import name_change_approval_kb
from bot.keyboards.common.profile_kb import profile_menu_kb
from bot.keyboards.utils.utils_kb import reg_name_conflict_kb


def _all_buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def test_profile_menu_kb_has_change_name_and_reminder_settings_buttons():
    markup = profile_menu_kb()

    texts_by_callback = {button.callback_data: button.text for button in _all_buttons(markup)}

    assert texts_by_callback["profile_change_name"] == "📝 Изменить ФИ"
    assert texts_by_callback["profile_reminder_settings"] == "🔔 Настройки уведомлений"
    assert len(texts_by_callback) == 2


def test_reg_name_conflict_kb_has_yes_and_no_buttons():
    markup = reg_name_conflict_kb()

    texts_by_callback = {button.callback_data: button.text for button in _all_buttons(markup)}

    assert texts_by_callback["reg_name_conflict_yes"] == "✅ Да"
    assert texts_by_callback["reg_name_conflict_no"] == "❌ Нет"
    assert len(texts_by_callback) == 2


def test_name_change_approval_kb_buttons_pack_action_and_user_id():
    markup = name_change_approval_kb(user_id=42)

    buttons = _all_buttons(markup)
    assert len(buttons) == 2

    approve_button, reject_button = buttons

    approve_data = NameChangeApprovalCB.unpack(approve_button.callback_data)
    reject_data = NameChangeApprovalCB.unpack(reject_button.callback_data)

    assert approve_button.text == "✅ Принять"
    assert approve_data.action == "approve"
    assert approve_data.user_id == 42

    assert reject_button.text == "❌ Отклонить"
    assert reject_data.action == "reject"
    assert reject_data.user_id == 42
