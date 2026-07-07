import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.exceptions.exceptions import BotException
from bot.models.appointment import Appointment
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.user_repository import UserRepository
from bot.services.appointment.appointment_notifications import (
    AppointmentNotificationService,
)
from bot.services.appointment.appointment_jobs import (
    send_reminder_job,
    mark_appointment_completed_job,
)
from bot.utils.appointment_enums import AppointmentStatus

logger = logging.getLogger(__name__)


class AppointmentScheduler:
    """Manages scheduled reminders for appointments using APScheduler.

    Responsibilities:
    - Schedule reminders 24h and 2h before appointment datetime
    - Send reminder messages with appointment response buttons
    - Cancel reminders when appointment status or datetime changes
    - Handle graceful cleanup of jobs
    """

    def __init__(
        self,
        scheduler: AsyncIOScheduler,
        appointment_repo: AppointmentRepository,
        user_repo: UserRepository,
        notification_service: AppointmentNotificationService,
    ):
        self.scheduler = scheduler
        self.appointment_repo = appointment_repo
        self.user_repo = user_repo
        self.notification_service = notification_service

    async def schedule_appointment_reminders(self, appointment: Appointment) -> None:
        """Schedule reminder jobs for an appointment.

        Creates two scheduled jobs:
        - One for 24 hours before appointment datetime
        - One for 2 hours before appointment datetime

        Job IDs follow pattern: appt_{appointment_id}_{hours}h
        """
        if not appointment.id:
            logger.warning("Cannot schedule reminders for appointment without ID")
            return

        try:
            appointment_dt = datetime.fromisoformat(appointment.datetime)

            reminder_times = [
                (appointment_dt - timedelta(hours=24), 24),
                (appointment_dt - timedelta(hours=2), 2),
            ]

            for reminder_dt, hours_before in reminder_times:
                job_id = f"appt_{appointment.id}_{hours_before}h"

                self.scheduler.add_job(
                    send_reminder_job,
                    "date",
                    run_date=reminder_dt,
                    args=(appointment.id,),
                    id=job_id,
                    replace_existing=True,
                )

                logger.info(
                    f"Scheduled reminder for appointment {appointment.id} "
                    f"at {reminder_dt.isoformat()}"
                )
        except BotException as e:
            logger.error(
                f"Failed to schedule reminders for appointment {appointment.id}: {e}"
            )

    async def cancel_appointment_reminders(self, appointment_id: int) -> None:
        """Cancel all scheduled reminders for an appointment.

        Removes jobs matching pattern: appt_{appointment_id}_*
        """
        from apscheduler.jobstores.base import JobLookupError

        try:
            job_ids_to_remove = [
                f"appt_{appointment_id}_24h",
                f"appt_{appointment_id}_2h",
            ]

            for job_id in job_ids_to_remove:
                try:
                    self.scheduler.remove_job(job_id)
                    logger.info(f"Cancelled reminder job: {job_id}")
                except JobLookupError:
                    logger.debug(f"Job {job_id} does not exist (already ran or cancelled)")
                except Exception as e:
                    logger.warning(f"Failed to remove job {job_id}: {e}")
        except Exception as e:
            logger.error(
                f"Failed to cancel reminders for appointment {appointment_id}: {e}"
            )

    async def schedule_appointment_completion(self, appointment: Appointment) -> None:
        """Schedule completion job for an appointment.

        Creates a scheduled job that runs 1 hour after appointment datetime
        to automatically mark the appointment as COMPLETED.

        Job ID: appt_{appointment_id}_complete
        """
        if not appointment.id:
            logger.warning("Cannot schedule completion for appointment without ID")
            return

        try:
            appointment_dt = datetime.fromisoformat(appointment.datetime)
            completion_time = appointment_dt + timedelta(hours=1)

            job_id = f"appt_{appointment.id}_complete"

            self.scheduler.add_job(
                mark_appointment_completed_job,
                "date",
                run_date=completion_time,
                args=(appointment.id,),
                id=job_id,
                replace_existing=True,
            )

            logger.info(
                f"Scheduled completion for appointment {appointment.id} "
                f"at {completion_time.isoformat()}"
            )
        except BotException as e:
            logger.error(
                f"Failed to schedule completion for appointment {appointment.id}: {e}"
            )

    async def cancel_appointment_completions(self, appointment_id: int) -> None:
        """Cancel completion job for an appointment.

        Removes job with ID: appt_{appointment_id}_complete
        """
        from apscheduler.jobstores.base import JobLookupError

        try:
            job_id = f"appt_{appointment_id}_complete"

            try:
                self.scheduler.remove_job(job_id)
                logger.info(f"Cancelled completion job: {job_id}")
            except JobLookupError:
                logger.debug(f"Completion job {job_id} does not exist (already ran or cancelled)")
            except Exception as e:
                logger.warning(f"Failed to remove completion job {job_id}: {e}")
        except Exception as e:
            logger.error(
                f"Failed to cancel completion for appointment {appointment_id}: {e}"
            )

    async def _send_reminder_job(self, appointment_id: int) -> None:
        """Wrapper for send_reminder_job - for backward compatibility with tests."""
        await send_reminder_job(appointment_id)

    async def _mark_appointment_completed_job(self, appointment_id: int) -> None:
        """Wrapper for mark_appointment_completed_job - for backward compatibility with tests."""
        await mark_appointment_completed_job(appointment_id)

