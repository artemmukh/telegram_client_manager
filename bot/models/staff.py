from dataclasses import dataclass


@dataclass
class Staff:
    telegram_user_id: int
    clinic_id: int
    # Access scope: whose data this staff member can see and manage.
    # "clinic" = all appointments of the clinic (reception admin, fan-out
    # recipient for staff logs); "own" = only their own appointments (doctor);
    # None = legacy/unknown, treated like "own" in scoping checks.
    # Use this column for permission checks, notification fan-out, and filters.
    visibility_scope: str | None = None

    # Professional role: whether this person can act as the performing doctor.
    # True = selectable in the doctor picker, labeled "Доктор ..." in logs.
    # False = non-performing staff (reception/manager), labeled "Администратор ...".
    # Use this column for doctor pickers, role labels, and card rendering.
    # NOTE: is_doctor and visibility_scope are independent dimensions; the
    # migration backfill below makes them coincide by default, but a doctor
    # may hold "clinic" scope and a reception admin is is_doctor=False.
    is_doctor: bool = True
