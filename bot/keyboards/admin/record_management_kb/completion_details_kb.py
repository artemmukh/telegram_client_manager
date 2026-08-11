from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.record_management_kb.completion_details_cb import (
    CompletionDetailsCB,
    CompletionHideDetailsCB,
)

_DETAILS_LABEL = {
    "ru": "Подробнее",
    "uz": "Batafsil",
}

_HIDE_DETAILS_LABEL = {
    "ru": "Скрыть",
    "uz": "Yopish",
}


def completion_details_kb(appointment_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_DETAILS_LABEL.get(lang, _DETAILS_LABEL["ru"]),
        callback_data=CompletionDetailsCB(appointment_id=appointment_id).pack(),
    )

    return builder.as_markup()


def completion_hide_details_kb(appointment_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_HIDE_DETAILS_LABEL.get(lang, _HIDE_DETAILS_LABEL["ru"]),
        callback_data=CompletionHideDetailsCB(appointment_id=appointment_id).pack(),
    )

    return builder.as_markup()
