from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.admin_reminder_cb import AdminReminderPresetCB

ADMIN_REMINDER_PRESET_LABELS = {
    "both": "🔔 За 24ч и за 2ч",
    "2_only": "🔔 Только за 2ч",
    "off": "🔕 Не напоминать",
}


def _active_preset(reminder_24h: bool, reminder_2h: bool) -> str:
    if reminder_24h and reminder_2h:
        return "both"
    if reminder_2h:
        return "2_only"
    return "off"


def admin_reminder_settings_kb(reminder_24h: bool, reminder_2h: bool) -> InlineKeyboardMarkup:
    active_preset = _active_preset(reminder_24h, reminder_2h)

    builder = InlineKeyboardBuilder()
    for preset, label in ADMIN_REMINDER_PRESET_LABELS.items():
        text = f"✅ {label}" if preset == active_preset else label
        builder.button(
            text=text,
            callback_data=AdminReminderPresetCB(preset=preset).pack(),
        )

    builder.adjust(1)
    return builder.as_markup()
