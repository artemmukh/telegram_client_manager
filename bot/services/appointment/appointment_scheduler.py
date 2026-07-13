import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.exceptions.appointment_exceptions import (
    JobSchedulingError,
    JobCancellationError,
)
from bot.models.appointment import Appointment
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.user_repository import UserRepository
from bot.services.appointment.appointment_notifications import (
    AppointmentNotificationService,
)
from bot.services.appointment.appointment_jobs import (
    send_reminder_job,
    mark_appointment_completed_job,
    complete_appointment,
    expire_pending_request_job,
    expire_reschedule_request_job,
    auto_confirm_pending_job,
)
from bot.services.utils.date_parser import get_current_tashkent_datetime as _current_tashkent_time
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy

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
            now = _current_tashkent_time()

            client = await self.user_repo.get_client_by_id(appointment.client_id)
            client_reminder_24h = client.reminder_24h if client else True
            client_reminder_2h = client.reminder_2h if client else True

            admin = await self.user_repo.get_user_by_telegram_id(appointment.created_by_telegram_id)
            admin_reminder_24h = admin.reminder_24h if admin else True
            admin_reminder_2h = admin.reminder_2h if admin else True

            reminder_times = []
            if client_reminder_24h or admin_reminder_24h:
                reminder_times.append((appointment_dt - timedelta(hours=24), 24, client_reminder_24h, admin_reminder_24h))
            if client_reminder_2h or admin_reminder_2h:
                reminder_times.append((appointment_dt - timedelta(hours=2), 2, client_reminder_2h, admin_reminder_2h))

            for reminder_dt, hours_before, client_wants_slot, admin_wants_slot in reminder_times:
                if reminder_dt <= now:
                    logger.info(
                        f"Skipping past-due {hours_before}h reminder for appointment "
                        f"{appointment.id} (would have run at {reminder_dt.isoformat()})"
                    )
                    continue

                job_id = f"appt_{appointment.id}_{hours_before}h"

                try:
                    self.scheduler.add_job(
                        send_reminder_job,
                        "date",
                        run_date=reminder_dt,
                        args=(appointment.id, hours_before, client_wants_slot, admin_wants_slot),
                        id=job_id,
                        replace_existing=True,
                    )
                except Exception as exc:
                    raise JobSchedulingError(
                        f"Failed to schedule reminder job {job_id}: {exc}"
                    ) from exc

                logger.info(
                    f"Scheduled reminder for appointment {appointment.id} "
                    f"at {reminder_dt.isoformat()}"
                )
        except JobSchedulingError as e:
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
                except Exception as exc:
                    raise JobCancellationError(
                        f"Failed to remove job {job_id}: {exc}"
                    ) from exc
        except JobCancellationError as e:
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

            if completion_time <= _current_tashkent_time():
                logger.info(
                    f"Skipping past-due completion for appointment {appointment.id} "
                    f"(would have run at {completion_time.isoformat()})"
                )
                return

            job_id = f"appt_{appointment.id}_complete"

            try:
                self.scheduler.add_job(
                    mark_appointment_completed_job,
                    "date",
                    run_date=completion_time,
                    args=(appointment.id,),
                    id=job_id,
                    replace_existing=True,
                )
            except Exception as exc:
                raise JobSchedulingError(
                    f"Failed to schedule completion job {job_id}: {exc}"
                ) from exc

            logger.info(
                f"Scheduled completion for appointment {appointment.id} "
                f"at {completion_time.isoformat()}"
            )
        except JobSchedulingError as e:
            logger.error(
                f"Failed to schedule completion for appointment {appointment.id}: {e}"
            )

    async def schedule_auto_confirm(self, appointment: Appointment) -> None:
        """Schedule auto-confirm job for a PENDING appointment.

        Creates a scheduled job that runs 2 hours before appointment datetime
        to automatically confirm PENDING appointments (after cancellation cutoff closes).

        Job ID: appt_{appointment_id}_autoconf
        """
        if not appointment.id:
            logger.warning("Cannot schedule auto-confirm for appointment without ID")
            return

        if appointment.status != AppointmentStatus.PENDING:
            logger.info(f"Skipping auto-confirm for appointment {appointment.id} "
                       f"with status {appointment.status.value}")
            return

        if appointment.created_by != CreatedBy.ADMIN:
            logger.info(f"Skipping auto-confirm for appointment {appointment.id} "
                       f"created by {appointment.created_by.value}")
            return

        try:
            appointment_dt = datetime.fromisoformat(appointment.datetime)
            autoconf_time = appointment_dt - timedelta(hours=2)

            if autoconf_time <= _current_tashkent_time():
                logger.info(
                    f"Skipping past-due auto-confirm for appointment {appointment.id} "
                    f"(would have run at {autoconf_time.isoformat()})"
                )
                return

            job_id = f"appt_{appointment.id}_autoconf"

            try:
                self.scheduler.add_job(
                    auto_confirm_pending_job,
                    "date",
                    run_date=autoconf_time,
                    args=(appointment.id,),
                    id=job_id,
                    replace_existing=True,
                )
            except Exception as exc:
                raise JobSchedulingError(
                    f"Failed to schedule auto-confirm job {job_id}: {exc}"
                ) from exc

            logger.info(
                f"Scheduled auto-confirm for appointment {appointment.id} "
                f"at {autoconf_time.isoformat()}"
            )
        except JobSchedulingError as e:
            logger.error(
                f"Failed to schedule auto-confirm for appointment {appointment.id}: {e}"
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
            except Exception as exc:
                raise JobCancellationError(
                    f"Failed to remove completion job {job_id}: {exc}"
                ) from exc
        except JobCancellationError as e:
            logger.error(
                f"Failed to cancel completion for appointment {appointment_id}: {e}"
            )

    async def cancel_auto_confirm(self, appointment_id: int) -> None:
        """Cancel auto-confirm job for an appointment.

        Removes job with ID: appt_{appointment_id}_autoconf
        """
        from apscheduler.jobstores.base import JobLookupError

        try:
            job_id = f"appt_{appointment_id}_autoconf"

            try:
                self.scheduler.remove_job(job_id)
                logger.info(f"Cancelled auto-confirm job: {job_id}")
            except JobLookupError:
                logger.debug(f"Auto-confirm job {job_id} does not exist (already ran or cancelled)")
            except Exception as exc:
                raise JobCancellationError(
                    f"Failed to remove auto-confirm job {job_id}: {exc}"
                ) from exc
        except JobCancellationError as e:
            logger.error(
                f"Failed to cancel auto-confirm for appointment {appointment_id}: {e}"
            )

    async def schedule_pending_expiry(self, appointment: Appointment) -> None:
        """Schedule an expiry job for a client self-booking request.

        Runs at the appointment's requested datetime; if the clinic has not
        responded by then, the request auto-expires.

        Job ID: appt_{appointment_id}_expire
        """
        if not appointment.id:
            logger.warning("Cannot schedule pending expiry for appointment without ID")
            return

        try:
            appointment_dt = datetime.fromisoformat(appointment.datetime)
            now = _current_tashkent_time()

            if appointment_dt <= now:
                logger.info(
                    f"Skipping past-due pending expiry for appointment {appointment.id} "
                    f"(would have run at {appointment_dt.isoformat()})"
                )
                return

            job_id = f"appt_{appointment.id}_expire"

            try:
                self.scheduler.add_job(
                    expire_pending_request_job,
                    "date",
                    run_date=appointment_dt,
                    args=(appointment.id,),
                    id=job_id,
                    replace_existing=True,
                )
            except Exception as exc:
                raise JobSchedulingError(
                    f"Failed to schedule pending expiry job {job_id}: {exc}"
                ) from exc

            logger.info(
                f"Scheduled pending expiry for appointment {appointment.id} "
                f"at {appointment_dt.isoformat()}"
            )
        except JobSchedulingError as e:
            logger.error(
                f"Failed to schedule pending expiry for appointment {appointment.id}: {e}"
            )

    async def cancel_pending_expiry(self, appointment_id: int) -> None:
        """Cancel the pending expiry job for an appointment.

        Removes job with ID: appt_{appointment_id}_expire
        """
        from apscheduler.jobstores.base import JobLookupError

        try:
            job_id = f"appt_{appointment_id}_expire"

            try:
                self.scheduler.remove_job(job_id)
                logger.info(f"Cancelled pending expiry job: {job_id}")
            except JobLookupError:
                logger.debug(f"Pending expiry job {job_id} does not exist (already ran or cancelled)")
            except Exception as exc:
                raise JobCancellationError(
                    f"Failed to remove pending expiry job {job_id}: {exc}"
                ) from exc
        except JobCancellationError as e:
            logger.error(
                f"Failed to cancel pending expiry for appointment {appointment_id}: {e}"
            )

    async def schedule_reschedule_expiry(self, appointment: Appointment) -> None:
        """Schedule an expiry job for a client-initiated reschedule request.

        Runs at the client's proposed datetime; if the clinic has not
        responded by then, the reschedule request auto-expires and the
        appointment quietly stays CONFIRMED at its original datetime.

        Job ID: appt_{appointment_id}_resch_expire
        """
        if not appointment.proposed_datetime:
            return

        if not appointment.id:
            logger.warning("Cannot schedule reschedule expiry for appointment without ID")
            return

        try:
            proposed_dt = datetime.fromisoformat(appointment.proposed_datetime)
            now = _current_tashkent_time()

            if proposed_dt <= now:
                logger.info(
                    f"Skipping past-due reschedule expiry for appointment {appointment.id} "
                    f"(would have run at {proposed_dt.isoformat()})"
                )
                return

            job_id = f"appt_{appointment.id}_resch_expire"

            try:
                self.scheduler.add_job(
                    expire_reschedule_request_job,
                    "date",
                    run_date=proposed_dt,
                    args=(appointment.id,),
                    id=job_id,
                    replace_existing=True,
                )
            except Exception as exc:
                raise JobSchedulingError(
                    f"Failed to schedule reschedule expiry job {job_id}: {exc}"
                ) from exc

            logger.info(
                f"Scheduled reschedule expiry for appointment {appointment.id} "
                f"at {proposed_dt.isoformat()}"
            )
        except JobSchedulingError as e:
            logger.error(
                f"Failed to schedule reschedule expiry for appointment {appointment.id}: {e}"
            )

    async def cancel_reschedule_expiry(self, appointment_id: int) -> None:
        """Cancel the reschedule expiry job for an appointment.

        Removes job with ID: appt_{appointment_id}_resch_expire
        """
        from apscheduler.jobstores.base import JobLookupError

        try:
            job_id = f"appt_{appointment_id}_resch_expire"

            try:
                self.scheduler.remove_job(job_id)
                logger.info(f"Cancelled reschedule expiry job: {job_id}")
            except JobLookupError:
                logger.debug(f"Reschedule expiry job {job_id} does not exist (already ran or cancelled)")
            except Exception as exc:
                raise JobCancellationError(
                    f"Failed to remove reschedule expiry job {job_id}: {exc}"
                ) from exc
        except JobCancellationError as e:
            logger.error(
                f"Failed to cancel reschedule expiry for appointment {appointment_id}: {e}"
            )

    async def _send_reminder_job(
        self,
        appointment_id: int,
        hours_before: int = 24,
        notify_client: bool = True,
        notify_admin: bool = True,
    ) -> None:
        """Wrapper for send_reminder_job - for backward compatibility with tests."""
        await send_reminder_job(appointment_id, hours_before, notify_client, notify_admin)

    async def _mark_appointment_completed_job(self, appointment_id: int) -> None:
        """Mark appointment completed using this scheduler's injected dependencies.

        Unlike mark_appointment_completed_job (which is scheduled by APScheduler
        via module reference and creates its own bot/repositories), this wrapper
        reuses appointment_repo and notification_service injected into this
        AppointmentScheduler instance.
        """
        await complete_appointment(
            self.appointment_repo,
            self.notification_service,
            appointment_id,
        )

