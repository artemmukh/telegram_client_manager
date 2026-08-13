from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.record_management_kb.appointment_log_details_cb import (
    AppointmentLogDetailsCB,
    AppointmentLogHideDetailsCB,
)

_DETAILS_LABEL = {"ru": "Подробнее", "uz": "Batafsil"}
_HIDE_DETAILS_LABEL = {"ru": "Скрыть", "uz": "Yopish"}


def appointment_log_details_kb(appointment_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_DETAILS_LABEL.get(lang, _DETAILS_LABEL["ru"]),
        callback_data=AppointmentLogDetailsCB(appointment_id=appointment_id).pack(),
    )
    return builder.as_markup()


def appointment_log_hide_details_kb(appointment_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_HIDE_DETAILS_LABEL.get(lang, _HIDE_DETAILS_LABEL["ru"]),
        callback_data=AppointmentLogHideDetailsCB(appointment_id=appointment_id).pack(),
    )
    return builder.as_markup()
