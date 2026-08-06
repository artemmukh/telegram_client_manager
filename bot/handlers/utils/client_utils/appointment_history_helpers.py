from datetime import datetime

from bot.models.appointment import Appointment
from bot.services.utils.date_parser import build_reschedule_proposal_line, format_datetime_for_display
from bot.services.utils.escape_html import escape_html
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy, status_label

_DATETIME_LABEL = {"ru": "Дата и время: {value}", "uz": "Sana va vaqt: {value}"}
_PURPOSE_LABEL = {"ru": "Услуга: {value}", "uz": "Xizmat: {value}"}
_STATUS_LABEL = {"ru": "Статус: {value}", "uz": "Holat: {value}"}
_CLINIC_LABEL = {"ru": "Клиника: {value}", "uz": "Klinika: {value}"}
_DOCTOR_LABEL = {"ru": "Врач: {value}", "uz": "Shifokor: {value}"}
_DOCTOR_PHONE_LABEL = {"ru": "Телефон врача: {value}", "uz": "Shifokor telefoni: {value}"}
_NO_CLINIC_INFO = {"ru": "Информация не доступна", "uz": "Ma'lumot mavjud emas"}


def _format_appointment_datetime(appointment: Appointment, lang: str = "ru") -> str:
    try:
        return format_datetime_for_display(datetime.fromisoformat(appointment.datetime), lang)
    except ValueError:
        return appointment.datetime


def _is_negotiating(appointment: Appointment) -> bool:
    return appointment.status == AppointmentStatus.CONFIRMED and appointment.proposed_datetime is not None


def build_history_button_text(appointment: Appointment, lang: str = "ru") -> str:
    label = status_label(appointment.status, lang)
    status_emoji = label.split()[0]
    display_datetime = _format_appointment_datetime(appointment, lang)
    marker = "🔁" if _is_negotiating(appointment) else ""
    return f"{marker}{status_emoji} {display_datetime}"


def build_history_card_text(appointment: Appointment, lang: str = "ru") -> str:
    display_datetime = _format_appointment_datetime(appointment, lang)

    lines = [_DATETIME_LABEL.get(lang, _DATETIME_LABEL["ru"]).format(value=display_datetime)]

    if appointment.purpose:
        lines.append(_PURPOSE_LABEL.get(lang, _PURPOSE_LABEL["ru"]).format(value=escape_html(appointment.purpose)))

    proposal_line = build_reschedule_proposal_line(appointment, viewer=CreatedBy.CLIENT, lang=lang)
    if proposal_line is not None:
        lines.append(proposal_line)

    lines.append(_STATUS_LABEL.get(lang, _STATUS_LABEL["ru"]).format(value=status_label(appointment.status, lang)))

    clinic_display = appointment.clinic_name or _NO_CLINIC_INFO.get(lang, _NO_CLINIC_INFO["ru"])
    lines.append(_CLINIC_LABEL.get(lang, _CLINIC_LABEL["ru"]).format(value=clinic_display))

    if appointment.doctor_full_name and appointment.doctor_is_doctor:
        lines.append(_DOCTOR_LABEL.get(lang, _DOCTOR_LABEL["ru"]).format(value=escape_html(appointment.doctor_full_name)))
        lines.append(
            _DOCTOR_PHONE_LABEL.get(lang, _DOCTOR_PHONE_LABEL["ru"]).format(value=appointment.doctor_phone or '—')
        )

    return "\n".join(lines)
