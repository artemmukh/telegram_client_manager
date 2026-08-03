from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.admin_reminder_cb import AdminReminderPresetCB

ADMIN_REMINDER_PRESET_LABELS = {
    "ru": {
        "both": "🔔 За 24ч и за 2ч",
        "2_only": "🔔 Только за 2ч",
        "off": "🔕 Не напоминать",
    },
    "uz": {
        "both": "🔔 24 soat va 2 soat oldin",
        "2_only": "🔔 Faqat 2 soat oldin",
        "off": "🔕 Eslatmasin",
    },
}


def _active_preset(reminder_24h: bool, reminder_2h: bool) -> str:
    if reminder_24h and reminder_2h:
        return "both"
    if reminder_2h:
        return "2_only"
    return "off"


def admin_reminder_settings_kb(reminder_24h: bool, reminder_2h: bool, lang: str = "ru") -> InlineKeyboardMarkup:
    active_preset = _active_preset(reminder_24h, reminder_2h)
    preset_labels = ADMIN_REMINDER_PRESET_LABELS.get(lang, ADMIN_REMINDER_PRESET_LABELS["ru"])

    builder = InlineKeyboardBuilder()
    for preset, label in preset_labels.items():
        text = f"✅ {label}" if preset == active_preset else label
        builder.button(
            text=text,
            callback_data=AdminReminderPresetCB(preset=preset).pack(),
        )

    builder.adjust(1)
    return builder.as_markup()
