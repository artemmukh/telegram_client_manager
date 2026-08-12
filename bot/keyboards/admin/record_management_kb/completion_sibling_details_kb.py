from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.record_management_kb.completion_sibling_details_cb import (
    CompletionSiblingDetailsCB,
    CompletionSiblingHideDetailsCB,
)

_DETAILS_LABEL = {
    "ru": "Подробнее",
    "uz": "Batafsil",
}

_HIDE_DETAILS_LABEL = {
    "ru": "Скрыть",
    "uz": "Yopish",
}


def completion_sibling_details_kb(
    appointment_id: int, actor_user_id: int, lang: str = "ru",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_DETAILS_LABEL.get(lang, _DETAILS_LABEL["ru"]),
        callback_data=CompletionSiblingDetailsCB(
            appointment_id=appointment_id, actor_user_id=actor_user_id,
        ).pack(),
    )

    return builder.as_markup()


def completion_sibling_hide_details_kb(
    appointment_id: int, actor_user_id: int, lang: str = "ru",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_HIDE_DETAILS_LABEL.get(lang, _HIDE_DETAILS_LABEL["ru"]),
        callback_data=CompletionSiblingHideDetailsCB(
            appointment_id=appointment_id, actor_user_id=actor_user_id,
        ).pack(),
    )

    return builder.as_markup()
