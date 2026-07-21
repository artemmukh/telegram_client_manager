"""MVP constants for the client self-booking wizard.

These are intentionally hardcoded and not DB-driven yet (see
docs/client_functionality_vision.md section 1). A future pass will make
working hours/days configurable per clinic/doctor.
"""

from datetime import datetime, timedelta

WORKING_HOURS_START = "10:30"
WORKING_HOURS_END = "18:00"
SLOT_STEP_MINUTES = 30
WORKING_WEEKDAYS = (0, 1, 2, 3, 4, 5)  # Mon=0 ... Sat=5, Sunday=6 is a day off
BOOKING_HORIZON_DAYS = 14
MAX_PENDING_REQUESTS_PER_CLIENT = 1
CANCELLATION_COOLDOWN_WINDOW_MINUTES = 5
MAX_CANCELLATIONS_PER_COOLDOWN_WINDOW = 3


def _generate_slots() -> tuple[str, ...]:
    start = datetime.strptime(WORKING_HOURS_START, "%H:%M")
    end = datetime.strptime(WORKING_HOURS_END, "%H:%M")
    step = timedelta(minutes=SLOT_STEP_MINUTES)

    slots = []
    current = start
    while current <= end:
        slots.append(current.strftime("%H:%M"))
        current += step

    return tuple(slots)


BOOKING_SLOTS = _generate_slots()
