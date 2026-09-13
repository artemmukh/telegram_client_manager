from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.models.appointment import Appointment


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


class StatusActor(Enum):
    """Party that performed the latest appointment status transition."""

    CLIENT = "client"
    STAFF = "staff"
    SYSTEM = "system"


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


_APPOINTMENT_DECISION_STATUS_LABELS = {
    AppointmentStatus.PENDING: {
        "ru": "🕐 ожидает подтверждения {party}",
        "uz": "🕐 {party} tasdig'ini kutmoqda",
    },
    AppointmentStatus.CONFIRMED: {
        "ru": "✅ подтверждено {party}",
        "uz": "✅ {party} tomonidan tasdiqlangan",
    },
    AppointmentStatus.CANCELLED: {
        "ru": "❌ отменена {party}",
        "uz": "❌ {party} tomonidan bekor qilingan",
    },
}

_DECISION_PARTY_LABELS = {
    "ru": {"doctor": "врачом", "client": "клиентом"},
    "uz": {"doctor": "shifokor", "client": "mijoz"},
}

_PENDING_PARTY_LABELS = {
    "ru": {"doctor": "врача", "client": "клиента"},
    "uz": {"doctor": "shifokor", "client": "mijoz"},
}


def status_label_with_decision_party(
    status: AppointmentStatus,
    created_by: CreatedBy,
    proposed_by: CreatedBy | None = None,
    status_actor: StatusActor | None = None,
    lang: str = "ru",
) -> str:
    """Render a status with the party expected to decide it.

    A plain client-created request waits for the doctor, while an
    admin-created invite waits for the client.  A persisted actor takes
    precedence after a reschedule demotes a booking back to pending; a
    counter-proposal overrides the legacy fallback because its proposer is the
    party that has already acted.
    Final confirmed/cancelled statuses use the persisted status actor.  Older
    rows without that value retain the creator-based fallback.
    """
    templates = _APPOINTMENT_DECISION_STATUS_LABELS.get(status)
    if templates is None:
        return status_label(status, lang)

    resolved_lang = lang if lang in templates else "ru"
    party = "doctor" if created_by == CreatedBy.CLIENT else "client"
    if status == AppointmentStatus.PENDING:
        if status_actor == StatusActor.STAFF:
            party = "client"
        elif status_actor == StatusActor.CLIENT:
            party = "doctor"
        elif proposed_by is not None:
            party = "doctor" if proposed_by == CreatedBy.CLIENT else "client"
    elif status_actor == StatusActor.CLIENT:
        party = "client"
    elif status_actor == StatusActor.STAFF:
        party = "doctor"

    party_labels = (
        _PENDING_PARTY_LABELS if status == AppointmentStatus.PENDING else _DECISION_PARTY_LABELS
    )
    return templates[resolved_lang].format(party=party_labels[resolved_lang][party])


def appointment_status_label(appointment: "Appointment", lang: str = "ru") -> str:
    """Render an appointment status with the relevant decision party."""
    return status_label_with_decision_party(
        appointment.status,
        appointment.created_by,
        appointment.proposed_by,
        appointment.status_actor,
        lang,
    )


def tab_label(status: AppointmentStatus, lang: str = "ru") -> str:
    entry = APPOINTMENT_TAB_LABELS.get(status)
    if entry is None:
        return status.value
    return entry.get(lang, entry.get("ru", status.value))
