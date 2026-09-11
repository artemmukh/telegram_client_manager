"""Pure scheduling rules for staff decision reminders."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from bot.models.appointment import Appointment
from bot.models.appointment_notification import AppointmentNotification
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy

BOOKING_DECISION_REMINDER_KIND = "booking_decision_reminder"
RESCHEDULE_DECISION_REMINDER_KIND = "reschedule_decision_reminder"
DECISION_REMINDER_KINDS = (
    BOOKING_DECISION_REMINDER_KIND,
    RESCHEDULE_DECISION_REMINDER_KIND,
)
DECISION_REMINDER_INTERVAL = timedelta(hours=12)
TASHKENT_TZ = ZoneInfo("Asia/Tashkent")


def decision_reminder_job_id(appointment_id: int, kind: str) -> str:
    return f"appt_{appointment_id}_{kind}"


def decision_reminder_source_kind(kind: str) -> str:
    if kind == BOOKING_DECISION_REMINDER_KIND:
        return "booking"
    if kind == RESCHEDULE_DECISION_REMINDER_KIND:
        return "reschedule"
    raise ValueError(f"Unsupported decision reminder kind: {kind}")


def decision_reminder_kind(appointment: Appointment) -> str | None:
    if (
        appointment.status == AppointmentStatus.PENDING
        and appointment.created_by == CreatedBy.CLIENT
        and appointment.proposed_datetime is None
    ):
        return BOOKING_DECISION_REMINDER_KIND

    if (
        appointment.status in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)
        and appointment.proposed_by == CreatedBy.CLIENT
        and appointment.proposed_datetime is not None
    ):
        return RESCHEDULE_DECISION_REMINDER_KIND

    return None


def parse_stored_datetime(value: str) -> datetime:
    """Parse an appointment datetime as a naive Tashkent datetime."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(TASHKENT_TZ).replace(tzinfo=None)


def parse_notification_created_at(value: str) -> datetime:
    """Parse SQLite CURRENT_TIMESTAMP (UTC) into naive Tashkent time."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(TASHKENT_TZ).replace(tzinfo=None)


def decision_reminder_deadline(appointment: Appointment, kind: str) -> datetime:
    target_value = appointment.proposed_datetime or appointment.datetime
    target = parse_stored_datetime(target_value)
    if kind == RESCHEDULE_DECISION_REMINDER_KIND and appointment.status == AppointmentStatus.CONFIRMED:
        return target
    return target - timedelta(hours=2)


def decision_reminder_origin(
    appointment: Appointment,
    kind: str,
    active_targets: list[AppointmentNotification],
) -> datetime | None:
    if not active_targets:
        return None

    if kind == BOOKING_DECISION_REMINDER_KIND:
        if appointment.created_at is None:
            return None
        return parse_stored_datetime(appointment.created_at)

    created_values = [target.created_at for target in active_targets if target.created_at]
    if not created_values:
        return None
    return min(parse_notification_created_at(value) for value in created_values)


def next_decision_reminder_run(
    origin: datetime,
    now: datetime,
    deadline: datetime,
) -> tuple[datetime, datetime] | None:
    """Return the next future run and the last strictly-before-deadline run."""
    if origin > now:
        first_run = origin + DECISION_REMINDER_INTERVAL
    else:
        elapsed = now - origin
        periods = int(elapsed.total_seconds() // DECISION_REMINDER_INTERVAL.total_seconds()) + 1
        first_run = origin + periods * DECISION_REMINDER_INTERVAL

    if first_run >= deadline:
        return None

    remaining = deadline - first_run
    last_period = int(
        max(0, (remaining - timedelta(microseconds=1)).total_seconds())
        // DECISION_REMINDER_INTERVAL.total_seconds()
    )
    return first_run, first_run + last_period * DECISION_REMINDER_INTERVAL
