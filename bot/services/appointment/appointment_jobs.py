"""Module-level job functions for APScheduler.

These functions must be at module level (not nested or bound methods) so APScheduler
can pickle them by reference (module.function_name) when persisting jobs to the database.

Each function creates its own database connection and services to remain independent
of the AppointmentScheduler instance.
"""

import logging

from bot.loader import get_bot
from bot.config.config import load_config
from bot.models.database import Database
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.user_repository import UserRepository
from bot.services.appointment.appointment_notifications import (
    AppointmentNotificationService,
)
from bot.services.utils.date_parser import get_current_tashkent_time
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.exceptions.appointment_exceptions import AppointmentNotFoundError, NotificationDeliveryError

logger = logging.getLogger(__name__)


async def send_reminder_job(
    appointment_id: int,
    hours_before: int = 24,
    notify_client: bool = True,
    notify_admin: bool = True,
) -> None:
    """Send appointment reminder to client and/or admin based on time until appointment.

    This job is called by APScheduler at scheduled reminder times (24h and 2h before).
    notify_client/notify_admin are captured at schedule time from each party's
    reminder preferences and must not be re-fetched here.

    Args:
        appointment_id: The ID of the appointment to send reminder for
        hours_before: Hours before appointment (24 or 2)
        notify_client: Whether the client wants this reminder slot
        notify_admin: Whether the admin wants this reminder slot
    """
    connection = None
    try:
        bot = get_bot()
        config = load_config()

        db = Database(config.database_path)
        connection = await db.connect()

        appointment_repo = AppointmentRepository(connection)
        user_repo = UserRepository(connection)
        notification_service = AppointmentNotificationService(bot, user_repo, appointment_repo)

        appointment = await appointment_repo.get_appointment_by_id(appointment_id)

        if appointment is None:
            logger.warning(
                f"Reminder job: appointment {appointment_id} not found"
            )
            return

        if appointment.status not in (
            AppointmentStatus.PENDING,
            AppointmentStatus.CONFIRMED,
        ):
            logger.info(
                f"Reminder job: skipping reminder for appointment {appointment_id} "
                f"with status {appointment.status.value}"
            )
            return

        # Get client info for potential admin notification
        client = await user_repo.get_client_by_id(appointment.client_id)
        client_name = client.full_name if client else "Неизвестный клиент"

        if hours_before not in (24, 2):
            logger.warning(f"Unknown reminder time: {hours_before}h")
            return

        # Determine reminder type and send to CLIENT
        reminder_type = f"{hours_before}h"

        if notify_client:
            notification_sent = False

            try:
                if hours_before == 24:
                    # 24h reminder: short reply, NO buttons
                    notification_sent = (
                        await notification_service.notify_client_reminder_without_buttons(appointment)
                    )
                    reminder_type = "24h (no buttons)"
                else:
                    # 2h reminder: short reply WITH buttons
                    notification_sent = (
                        await notification_service.notify_client_reminder_with_buttons(appointment)
                    )
                    reminder_type = "2h (with buttons)"

                if notification_sent:
                    logger.info(
                        f"Reminder sent for appointment {appointment_id} ({reminder_type})"
                    )
                else:
                    logger.warning(
                        f"Failed to send {reminder_type} reminder for appointment {appointment_id} "
                        f"(client not found or no telegram_id)"
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to send client reminder for appointment {appointment_id} ({hours_before}h): {e}"
                )
                # Still allow admin notification to be sent
                reminder_type = f"{hours_before}h (failed)"

        # Send reminder to ADMIN (INDEPENDENT, must always attempt)
        if notify_admin and appointment.created_by_telegram_id and client:
            try:
                await notification_service.notify_admin_upcoming_appointment(
                    appointment.created_by_telegram_id,
                    appointment,
                    client_name,
                )
                logger.info(
                    f"Admin reminder sent for appointment {appointment_id} ({reminder_type})"
                )
            except NotificationDeliveryError as e:
                logger.warning(
                    f"Failed to send admin reminder for appointment {appointment_id}: {e}"
                )
            except Exception as e:
                logger.exception(
                    f"Unexpected error sending admin reminder for appointment {appointment_id}: {e}"
                )

    except AppointmentNotFoundError:
        logger.warning(f"Send reminder job: appointment {appointment_id} not found")
    except Exception as e:
        logger.exception(
            f"Error in send_reminder_job({appointment_id}): {e}"
        )
    finally:
        if connection is not None:
            await connection.close()


async def complete_appointment(
    appointment_repo: AppointmentRepository,
    notification_service: AppointmentNotificationService,
    appointment_id: int,
) -> None:
    """Mark appointment as completed and notify the admin.

    Shared by the standalone APScheduler job function and by
    AppointmentScheduler (for callers that inject repositories/notification
    service directly, e.g. tests).

    Updates status to COMPLETED if appointment is still PENDING or CONFIRMED.

    Args:
        appointment_repo: Repository used to fetch/update the appointment
        notification_service: Service used to notify the admin
        appointment_id: The ID of the appointment to mark as completed
    """
    appointment = await appointment_repo.get_appointment_by_id(appointment_id)

    if appointment is None:
        logger.warning(
            f"Completion job: appointment {appointment_id} not found"
        )
        return

    if appointment.status in (
        AppointmentStatus.CANCELLED,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.NO_SHOW,
        AppointmentStatus.EXPIRED,
    ):
        logger.info(
            f"Completion job: skipping appointment {appointment_id} "
            f"with status {appointment.status.value}"
        )
        return

    await appointment_repo.update_appointment_status(
        appointment_id,
        AppointmentStatus.COMPLETED,
        get_current_tashkent_time(),
    )

    logger.info(
        f"Appointment {appointment_id} auto-completed"
    )

    if appointment.created_by_telegram_id:
        try:
            await notification_service.notify_admin_completion(
                appointment.created_by_telegram_id, appointment
            )
            logger.info(
                f"Sent completion notification to admin for appointment {appointment_id}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to send completion notification to admin for appointment {appointment_id}: {e}"
            )


async def expire_pending_request_job(appointment_id: int) -> None:
    """Expire an unanswered client self-booking request once its requested time passes.

    This job is called by APScheduler at the appointment's requested datetime
    (or, if the clinic proposed a new time, at the proposed datetime).

    Args:
        appointment_id: The ID of the appointment/request to expire
    """
    connection = None
    try:
        bot = get_bot()
        config = load_config()

        db = Database(config.database_path)
        connection = await db.connect()

        appointment_repo = AppointmentRepository(connection)
        user_repo = UserRepository(connection)
        notification_service = AppointmentNotificationService(bot, user_repo, appointment_repo)

        appointment = await appointment_repo.get_appointment_by_id(appointment_id)

        if appointment is None:
            logger.warning(f"Expire pending job: appointment {appointment_id} not found")
            return

        if appointment.status != AppointmentStatus.PENDING or appointment.created_by != CreatedBy.CLIENT:
            logger.info(
                f"Expire pending job: skipping appointment {appointment_id} "
                f"(status={appointment.status.value}, created_by={appointment.created_by.value})"
            )
            return

        await appointment_repo.update_appointment_status(
            appointment_id, AppointmentStatus.EXPIRED, get_current_tashkent_time()
        )

        logger.info(f"Appointment {appointment_id} self-booking request expired (unanswered)")

        try:
            await notification_service.notify_client_pending_request_expired(appointment)
        except Exception as e:
            logger.warning(
                f"Failed to send expiry notification to client for appointment {appointment_id}: {e}"
            )

        if appointment.proposed_datetime is not None:
            if appointment.proposal_message_id:
                try:
                    client = await user_repo.get_client_by_id(appointment.client_id)
                    if client and client.telegram_user_id:
                        await notification_service.close_reschedule_proposal_message(
                            client.telegram_user_id, appointment.proposal_message_id
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to close stale proposal message for appointment {appointment_id}: {e}"
                    )

            await appointment_repo.update_proposed_datetime(appointment_id, None)
            await appointment_repo.update_proposal_message_id(appointment_id, None)
            await appointment_repo.update_proposed_by(appointment_id, None)

    except AppointmentNotFoundError:
        logger.warning(f"Expire pending job: appointment {appointment_id} not found")
    except Exception as e:
        logger.exception(f"Error in expire_pending_request_job({appointment_id}): {e}")
    finally:
        if connection is not None:
            await connection.close()


async def expire_reschedule_request_job(appointment_id: int) -> None:
    """Expire an unanswered client-initiated reschedule request once the proposed time passes.

    This job is called by APScheduler at the client's proposed datetime. Unlike
    expire_pending_request_job, it does NOT change the appointment status: the
    appointment stays CONFIRMED at its ORIGINAL datetime, only the outstanding
    proposal is cleared. Reminder/completion jobs for the original time were never
    touched during the negotiation, so they continue to fire normally.

    Args:
        appointment_id: The ID of the appointment whose reschedule request should expire
    """
    connection = None
    try:
        bot = get_bot()
        config = load_config()

        db = Database(config.database_path)
        connection = await db.connect()

        appointment_repo = AppointmentRepository(connection)
        user_repo = UserRepository(connection)
        notification_service = AppointmentNotificationService(bot, user_repo, appointment_repo)

        appointment = await appointment_repo.get_appointment_by_id(appointment_id)

        if appointment is None:
            logger.warning(f"Reschedule expiry job: appointment {appointment_id} not found")
            return

        if (
            appointment.status != AppointmentStatus.CONFIRMED
            or appointment.proposed_datetime is None
            or appointment.proposed_by != CreatedBy.CLIENT
        ):
            logger.info(f"Reschedule expiry job: skipping appointment {appointment_id} (already resolved)")
            return

        await appointment_repo.update_proposed_datetime(appointment_id, None)
        await appointment_repo.update_proposed_by(appointment_id, None)

        logger.info(f"Reschedule request for appointment {appointment_id} expired (unanswered)")

        try:
            await notification_service.notify_client_reschedule_request_expired(appointment)
        except Exception as e:
            logger.warning(
                f"Failed to send reschedule-expiry notification for appointment {appointment_id}: {e}"
            )

    except AppointmentNotFoundError:
        logger.warning(f"Reschedule expiry job: appointment {appointment_id} not found")
    except Exception as e:
        logger.exception(f"Error in expire_reschedule_request_job({appointment_id}): {e}")
    finally:
        if connection is not None:
            await connection.close()


async def mark_appointment_completed_job(appointment_id: int) -> None:
    """Mark appointment as completed (called 1 hour after appointment time).

    This job is called by APScheduler 1 hour after the appointment datetime.
    Creates its own bot/repositories so it can be scheduled by module reference.

    Args:
        appointment_id: The ID of the appointment to mark as completed
    """
    connection = None
    try:
        bot = get_bot()
        config = load_config()

        db = Database(config.database_path)
        connection = await db.connect()

        appointment_repo = AppointmentRepository(connection)
        user_repo = UserRepository(connection)
        notification_service = AppointmentNotificationService(bot, user_repo, appointment_repo)

        await complete_appointment(appointment_repo, notification_service, appointment_id)

    except AppointmentNotFoundError:
        logger.warning(f"Mark completion job: appointment {appointment_id} not found")
    except Exception as e:
        logger.exception(
            f"Error in mark_appointment_completed_job({appointment_id}): {e}"
        )
    finally:
        if connection is not None:
            await connection.close()
