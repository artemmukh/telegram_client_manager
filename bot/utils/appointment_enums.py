from enum import Enum


class AppointmentStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"
    EXPIRED = "expired"


class CreatedBy(Enum):
    ADMIN = "admin"
    CLIENT = "client"


APPOINTMENT_STATUS_LABELS = {
    AppointmentStatus.PENDING: {"ru": "🕐 ожидает", "uz": "🕐 kutilmoqda"},
    AppointmentStatus.CONFIRMED: {"ru": "✅ подтверждена", "uz": "✅ tasdiqlangan"},
    AppointmentStatus.CANCELLED: {"ru": "❌ отменена", "uz": "❌ bekor qilingan"},
    AppointmentStatus.COMPLETED: {"ru": "✔️ завершена", "uz": "✔️ yakunlangan"},
    AppointmentStatus.NO_SHOW: {"ru": "🙅 неявка", "uz": "🙅 kelmadi"},
    AppointmentStatus.EXPIRED: {"ru": "⏳ истекла", "uz": "⏳ muddati o'tgan"},
}

APPOINTMENT_TAB_ORDER = [
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.PENDING,
    AppointmentStatus.CANCELLED,
    AppointmentStatus.NO_SHOW,
    AppointmentStatus.COMPLETED,
    AppointmentStatus.EXPIRED,
]

APPOINTMENT_TAB_LABELS = {
    AppointmentStatus.CONFIRMED: {"ru": "✅ Подтверждённые", "uz": "✅ Tasdiqlangan"},
    AppointmentStatus.PENDING: {"ru": "🕐 Ожидание", "uz": "🕐 Kutilmoqda"},
    AppointmentStatus.CANCELLED: {"ru": "❌ Отменённые", "uz": "❌ Bekor qilingan"},
    AppointmentStatus.NO_SHOW: {"ru": "🙅 Неявка", "uz": "🙅 Kelmadi"},
    AppointmentStatus.COMPLETED: {"ru": "✔️ Завершённые", "uz": "✔️ Yakunlangan"},
    AppointmentStatus.EXPIRED: {"ru": "⏳ Истёкшие", "uz": "⏳ Muddati o'tgan"},
}


def status_label(status: AppointmentStatus, lang: str = "ru") -> str:
    entry = APPOINTMENT_STATUS_LABELS.get(status)
    if entry is None:
        return status.value
    return entry.get(lang, entry.get("ru", status.value))


def tab_label(status: AppointmentStatus, lang: str = "ru") -> str:
    entry = APPOINTMENT_TAB_LABELS.get(status)
    if entry is None:
        return status.value
    return entry.get(lang, entry.get("ru", status.value))
