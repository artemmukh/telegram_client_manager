"""Per-instance clinic identity, shared by ClinicRepository and StaffRepository.

Each bot instance ("zb" / "mm") now runs against its own dedicated database
(one clinic per DB) instead of one shared multi-clinic database. This module
is the single place that maps an instance name to its clinic's name/token and
its initial staff telegram ids, so the two repositories don't each hardcode
their own copy of the same business data.
"""

from typing import TypedDict


class ClinicSeed(TypedDict):
    name: str
    token: str


CLINIC_SEED_BY_INSTANCE: dict[str, ClinicSeed] = {
    "zb": {"name": "Зуб Мудрости", "token": "x7A92JdPkLmQe81"},
    "mm": {"name": "Мануал Мед", "token": "q5N28JdTkLmXe73"},
}

STAFF_SEED_BY_INSTANCE: dict[str, list[int]] = {
    "zb": [685889801, 226655040, 37470594],
    # 685889801 is also an admin here: now that zb/mm are separate databases
    # (not one shared DB), the same telegram id can be staff in both without
    # the staff.telegram_user_id PK conflict that blocked this before.
    "mm": [1093653116, 685889801],
}
