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
    AppointmentStatus.PENDING: "🕐 ожидает",
    AppointmentStatus.CONFIRMED: "✅ подтверждена",
    AppointmentStatus.CANCELLED: "❌ отменена",
    AppointmentStatus.COMPLETED: "✔️ завершена",
    AppointmentStatus.NO_SHOW: "🙅 неявка",
    AppointmentStatus.EXPIRED: "⏳ истекла",
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
    AppointmentStatus.CONFIRMED: "✅ Подтверждённые",
    AppointmentStatus.PENDING: "🕐 Ожидание",
    AppointmentStatus.CANCELLED: "❌ Отменённые",
    AppointmentStatus.NO_SHOW: "🙅 Неявка",
    AppointmentStatus.COMPLETED: "Завершённые",
    AppointmentStatus.EXPIRED: "⏳ Истёкшие",
}
