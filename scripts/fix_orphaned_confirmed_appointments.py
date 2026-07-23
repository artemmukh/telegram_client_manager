#!/usr/bin/env python3
"""
One-off remediation: complete CONFIRMED appointments whose autocomplete window
already passed (e.g. appointment #39), left stuck because
schedule_appointment_autocomplete used to silently no-op on a past-due
autocomplete_time instead of completing the appointment. That guard is now
fixed going forward (see bot/services/appointment/appointment_scheduler.py),
but this script cleans up any appointment that already got stuck under the
old, buggy behavior.

Usage:
    python scripts/fix_orphaned_confirmed_appointments.py

Safe to re-run: only touches appointments that are still CONFIRMED with no
active reschedule negotiation and whose autocomplete window has passed;
completed appointments are skipped on subsequent runs.

WARNING: This mutates production data. Back up the database before running
against production.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from bot.config.config import load_config
from bot.models.database import Database
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.client_clinic_repository import ClientClinicRepository
from bot.repositories.staff_repository import StaffRepository
from bot.repositories.user_repository import UserRepository
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_scheduler import AUTO_COMPLETE_DELAY_HOURS
from bot.services.utils.date_parser import get_current_tashkent_datetime
from bot.utils.appointment_enums import AppointmentStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def _get_clinic_ids(clinic_repository: ClinicRepository) -> list[int]:
    cursor = await clinic_repository.connection.execute("SELECT id FROM clinics")
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def fix_orphaned_confirmed_appointments() -> None:
    db = Database(load_config().database_path)
    connection = await db.connect()

    try:
        appointment_repo = AppointmentRepository(connection)
        user_repo = UserRepository(connection)
        staff_repo = StaffRepository(connection)
        clinic_repo = ClinicRepository(connection)
        client_clinic_repo = ClientClinicRepository(connection)

        await appointment_repo.init()
        await user_repo.init()
        await staff_repo.init()
        await clinic_repo.init()
        await client_clinic_repo.init()

        appointment_management = AppointmentManagement(
            appointment_repo, user_repo, staff_repo, clinic_repo,
            client_clinic_repository=client_clinic_repo,
        )

        now = get_current_tashkent_datetime()
        touched = 0

        for clinic_id in await _get_clinic_ids(clinic_repo):
            page = 1
            while True:
                appointments = await appointment_repo.get_appointments_by_status_page(
                    status=AppointmentStatus.CONFIRMED,
                    page=page,
                    clinic_id=clinic_id,
                )
                if not appointments:
                    break

                for appointment in appointments:
                    if appointment.proposed_datetime is not None:
                        continue

                    appointment_dt = datetime.fromisoformat(appointment.datetime)
                    autocomplete_time = appointment_dt + timedelta(hours=AUTO_COMPLETE_DELAY_HOURS)

                    if autocomplete_time > now:
                        continue

                    logger.warning(
                        f"Completing orphaned CONFIRMED appointment {appointment.id} "
                        f"(autocomplete was due at {autocomplete_time.isoformat()})"
                    )
                    await appointment_management.complete_confirmed_appointment(appointment.id)
                    touched += 1

                page += 1

        logger.warning(f"Done. Completed {touched} orphaned CONFIRMED appointment(s).")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(fix_orphaned_confirmed_appointments())
