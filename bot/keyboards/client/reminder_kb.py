from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.client.reminder_cb import ClientReminderPresetCB

REMINDER_PRESET_LABELS = {
    "ru": {
        "both": "🔔 За 24ч и за 2ч",
        "24_only": "🔔 Только за 24ч",
        "2_only": "🔔 Только за 2ч",
        "off": "🔕 Не напоминать",
    },
    "uz": {
        "both": "🔔 24 soat va 2 soat oldin",
        "24_only": "🔔 Faqat 24 soat oldin",
        "2_only": "🔔 Faqat 2 soat oldin",
        "off": "🔕 Eslatmasin",
    },
}


def _active_preset(reminder_24h: bool, reminder_2h: bool) -> str:
    if reminder_24h and reminder_2h:
        return "both"
    if reminder_24h:
        return "24_only"
    if reminder_2h:
        return "2_only"
    return "off"


def reminder_settings_kb(reminder_24h: bool, reminder_2h: bool, lang: str = "ru") -> InlineKeyboardMarkup:
    active_preset = _active_preset(reminder_24h, reminder_2h)
    preset_labels = REMINDER_PRESET_LABELS.get(lang, REMINDER_PRESET_LABELS["ru"])

    builder = InlineKeyboardBuilder()
    for preset, label in preset_labels.items():
        text = f"✅ {label}" if preset == active_preset else label
        builder.button(
            text=text,
            callback_data=ClientReminderPresetCB(preset=preset).pack(),
        )

    builder.adjust(1)
    return builder.as_markup()
