from datetime import datetime

from bot.models.appointment import Appointment
from bot.services.utils.date_parser import format_datetime_for_display
from bot.services.utils.escape_html import escape_html
from bot.utils.appointment_enums import status_label

_ID_LABEL = {"ru": "Запись №{value}", "uz": "Yozuv №{value}"}
_DATETIME_LABEL = {"ru": "Дата и время: {value}", "uz": "Sana va vaqt: {value}"}
_PURPOSE_LABEL = {"ru": "Услуга: {value}", "uz": "Xizmat: {value}"}
_STATUS_LABEL = {"ru": "Статус: {value}", "uz": "Holat: {value}"}
_CLINIC_LABEL = {"ru": "Клиника: {value}", "uz": "Klinika: {value}"}
_DOCTOR_LABEL = {"ru": "Врач: {value}", "uz": "Shifokor: {value}"}
_DOCTOR_PHONE_LABEL = {"ru": "Телефон врача: {value}", "uz": "Shifokor telefoni: {value}"}
_NO_CLINIC_INFO = {"ru": "Информация недоступна", "uz": "Ma'lumot mavjud emas"}


def _format_datetime(value: str, lang: str) -> str:
    try:
        return format_datetime_for_display(datetime.fromisoformat(value), lang)
    except ValueError:
        return value


def build_client_appointment_log_details(appointment: Appointment, lang: str = "ru") -> str:
    """Render only the fields a client can normally view for a delivered log."""
    lines = [_ID_LABEL.get(lang, _ID_LABEL["ru"]).format(value=appointment.id)]
    clinic = appointment.clinic_name or _NO_CLINIC_INFO.get(lang, _NO_CLINIC_INFO["ru"])
    lines.append(_CLINIC_LABEL.get(lang, _CLINIC_LABEL["ru"]).format(value=escape_html(clinic)))
    lines.append(_DATETIME_LABEL.get(lang, _DATETIME_LABEL["ru"]).format(value=_format_datetime(appointment.datetime, lang)))
    if appointment.purpose:
        lines.append(_PURPOSE_LABEL.get(lang, _PURPOSE_LABEL["ru"]).format(value=escape_html(appointment.purpose)))
    lines.append(_STATUS_LABEL.get(lang, _STATUS_LABEL["ru"]).format(value=status_label(appointment.status, lang)))
    if appointment.doctor_full_name and appointment.doctor_is_doctor:
        lines.append(_DOCTOR_LABEL.get(lang, _DOCTOR_LABEL["ru"]).format(value=escape_html(appointment.doctor_full_name)))
        lines.append(
            _DOCTOR_PHONE_LABEL.get(lang, _DOCTOR_PHONE_LABEL["ru"]).format(
                value=appointment.doctor_phone or "—"
            )
        )
    return "\n".join(lines)
