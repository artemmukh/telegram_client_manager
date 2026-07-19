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
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.staff_repository import StaffRepository
from bot.repositories.user_repository import UserRepository
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import (
    AppointmentNotificationService,
)
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
    Client and admin reminder preferences are read fresh from the database at send
    time, not at schedule time, so a preference change between scheduling and firing
    takes effect immediately instead of being frozen at whatever it was when the job
    was created.

    The notify_client/notify_admin parameters remain in the signature only for
    backward compatibility with jobs already persisted to the job store (which call
    this function with 4 positional args); they are accepted but no longer used to
    decide anything.

    Args:
        appointment_id: The ID of the appointment to send reminder for
        hours_before: Hours before appointment (24 or 2)
        notify_client: Unused, kept for backward compatibility with persisted jobs
        notify_admin: Unused, kept for backward compatibility with persisted jobs
    """
    connection = None
    try:
        bot = get_bot()
        config = load_config()

        db = Database(config.database_path)
        connection = await db.connect()

        appointment_repo = AppointmentRepository(connection)
        user_repo = UserRepository(connection)
        staff_repo = StaffRepository(connection)
        clinic_repo = ClinicRepository(connection)
        appointment_management = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)
        notification_service = AppointmentNotificationService(bot, user_repo, appointment_repo)

        appointment = await appointment_management.get_appointment_by_id(appointment_id)

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
        client = await appointment_management.get_client_by_id(appointment.client_id)
        client_name = client.full_name if client else "Неизвестный клиент"

        if hours_before not in (24, 2):
            logger.warning(f"Unknown reminder time: {hours_before}h")
            return

        # Determine reminder type and send to CLIENT
        reminder_type = f"{hours_before}h"

        if hours_before == 24:
            client_wants = client.reminder_24h if client else True
        else:
            client_wants = client.reminder_2h if client else True

        if client_wants:
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
        if client:
            try:
                recipients = await appointment_management.resolve_notification_recipients(appointment)
            except Exception as e:
                logger.warning(
                    f"Failed to resolve notification recipients for appointment {appointment_id}: {e}"
                )
                recipients = []
            for recipient in recipients:
                recipient_wants = recipient.reminder_24h if hours_before == 24 else recipient.reminder_2h
                if not recipient_wants:
                    continue

                try:
                    await notification_service.notify_admin_upcoming_appointment(
                        recipient.telegram_user_id,
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
    appointment_management: AppointmentManagement,
    notification_service: AppointmentNotificationService,
    appointment_id: int,
) -> None:
    """Ask the admin whether to make post-appointment corrections.

    Shared by the standalone APScheduler job function and by
    AppointmentScheduler (for callers that inject repositories/notification
    service directly, e.g. tests).

    Fires 1 hour after the appointment. Does NOT change the appointment's
    status - it stays PENDING/CONFIRMED until the admin answers the prompt
    (see appointment_completion.py handlers).

    Args:
        appointment_management: Service used to fetch the appointment
        notification_service: Service used to notify the admin
        appointment_id: The ID of the appointment that just finished
    """
    appointment = await appointment_management.get_appointment_by_id(appointment_id)

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

    try:
        recipients = await appointment_management.resolve_notification_recipients(appointment)
    except Exception as e:
        logger.warning(
            f"Failed to resolve notification recipients for appointment {appointment_id}: {e}"
        )
        recipients = []

    for recipient in recipients:
        try:
            await notification_service.notify_admin_completion(
                recipient.telegram_user_id, appointment
            )
            logger.info(
                f"Sent completion notification to admin for appointment {appointment_id}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to send completion notification to admin for appointment {appointment_id}: {e}"
            )


async def expire_pending_request_job(appointment_id: int) -> None:
    """Expire an unanswered PENDING request 2 hours before its requested datetime.

    This job is called by APScheduler 2 hours before the appointment's requested datetime.
    Prevents stale requests from remaining open during the 2h reminder window. By the time
    this job fires, any PENDING appointment is by definition unanswered, regardless of
    created_by/proposed_datetime: a client self-booking request the clinic never answered,
    an admin-created invite the client never answered, or an admin-created appointment
    where the client proposed their own time and the admin never answered that
    counter-proposal.

    Note: For proposed/rescheduled times on a CONFIRMED appointment, see
    expire_reschedule_request_job().

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
        staff_repo = StaffRepository(connection)
        clinic_repo = ClinicRepository(connection)
        appointment_management = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)
        notification_service = AppointmentNotificationService(bot, user_repo, appointment_repo)

        appointment = await appointment_management.expire_pending_request(appointment_id)

        if appointment is None:
            logger.warning(f"Expire pending job: appointment {appointment_id} not found or not eligible")
            return

        logger.info(f"Appointment {appointment_id} pending request expired (unanswered)")

        try:
            await notification_service.notify_client_pending_request_expired(appointment)
        except Exception as e:
            logger.warning(
                f"Failed to send expiry notification to client for appointment {appointment_id}: {e}"
            )

        if appointment.proposed_datetime is not None:
            if appointment.proposal_message_id:
                try:
                    client = await appointment_management.get_client_by_id(appointment.client_id)
                    if client and client.telegram_user_id:
                        await notification_service.close_reschedule_proposal_message(
                            client.telegram_user_id, appointment.proposal_message_id
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to close stale proposal message for appointment {appointment_id}: {e}"
                    )

            await appointment_management.clear_proposal_state(appointment_id)

    except AppointmentNotFoundError:
        logger.warning(f"Expire pending job: appointment {appointment_id} not found")
    except Exception as e:
        logger.exception(f"Error in expire_pending_request_job({appointment_id}): {e}")
    finally:
        if connection is not None:
            await connection.close()


async def expire_reschedule_request_job(appointment_id: int) -> None:
    """Expire an unanswered reschedule proposal on a CONFIRMED appointment, from either side.

    This job is called by APScheduler at the proposed datetime, regardless of whether
    the proposal was made by the client (awaiting the clinic's answer) or by the admin
    (awaiting the client's answer). It does NOT change the appointment status: the
    appointment stays CONFIRMED at its ORIGINAL datetime, only the outstanding proposal
    is cleared.

    Note: for a PENDING+ADMIN appointment the client countered with their own time,
    see expire_pending_request_job() instead — that request expires via pending_expiry,
    not this job.

    Args:
        appointment_id: The ID of the appointment whose reschedule proposal should expire
    """
    connection = None
    try:
        bot = get_bot()
        config = load_config()

        db = Database(config.database_path)
        connection = await db.connect()

        appointment_repo = AppointmentRepository(connection)
        user_repo = UserRepository(connection)
        staff_repo = StaffRepository(connection)
        clinic_repo = ClinicRepository(connection)
        appointment_management = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)
        notification_service = AppointmentNotificationService(bot, user_repo, appointment_repo)

        appointment = await appointment_management.expire_reschedule_request(appointment_id)

        if appointment is None:
            logger.info(f"Reschedule expiry job: skipping appointment {appointment_id} (not found or already resolved)")
            return

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


async def send_proposal_reminder_job(appointment_id: int) -> None:
    """Remind whichever side has not yet answered an outstanding proposed time.

    Fires 3 hours before the proposed datetime (1 hour before the request would
    auto-expire via expire_pending_request_job/expire_reschedule_request_job).
    Covers all 4 negotiation directions: PENDING self-booking countered by the
    clinic, PENDING admin-invite countered by the client, CONFIRMED appointment
    with a clinic-proposed reschedule, and CONFIRMED appointment with a
    client-requested reschedule. The recipient is always the side that is NOT
    proposed_by. Does not change the appointment's state, only notifies.

    Args:
        appointment_id: The ID of the appointment/request to remind about
    """
    connection = None
    try:
        bot = get_bot()
        config = load_config()

        db = Database(config.database_path)
        connection = await db.connect()

        appointment_repo = AppointmentRepository(connection)
        user_repo = UserRepository(connection)
        staff_repo = StaffRepository(connection)
        clinic_repo = ClinicRepository(connection)
        appointment_management = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)
        notification_service = AppointmentNotificationService(bot, user_repo, appointment_repo)

        appointment = await appointment_management.get_appointment_by_id(appointment_id)

        if appointment is None:
            logger.warning(f"Proposal reminder job: appointment {appointment_id} not found")
            return

        if (
            appointment.status not in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)
            or appointment.proposed_datetime is None
        ):
            logger.info(f"Proposal reminder job: skipping appointment {appointment_id} (already resolved)")
            return

        try:
            notification_sent = False

            if appointment.proposed_by == CreatedBy.ADMIN:
                if appointment.status == AppointmentStatus.PENDING:
                    notification_sent = await notification_service.notify_client_proposal_reminder(appointment)
                else:
                    notification_sent = await notification_service.notify_client_appointment_reschedule_reminder(
                        appointment
                    )
            else:
                try:
                    recipients = await appointment_management.resolve_notification_recipients(appointment)
                except Exception as e:
                    logger.warning(
                        f"Failed to resolve notification recipients for appointment {appointment_id}: {e}"
                    )
                    recipients = []
                for recipient in recipients:
                    try:
                        await notification_service.notify_admin_proposal_reminder(
                            recipient.telegram_user_id, appointment
                        )
                        notification_sent = True
                    except Exception as e:
                        logger.warning(
                            f"Failed to send proposal reminder to admin for appointment {appointment_id}: {e}"
                        )

            if notification_sent:
                logger.info(f"Proposal reminder sent for appointment {appointment_id}")
            else:
                logger.warning(
                    f"Failed to send proposal reminder for appointment {appointment_id} "
                    f"(recipient not found or no telegram_id)"
                )
        except Exception as e:
            logger.warning(
                f"Failed to send proposal reminder for appointment {appointment_id}: {e}"
            )

    except AppointmentNotFoundError:
        logger.warning(f"Proposal reminder job: appointment {appointment_id} not found")
    except Exception as e:
        logger.exception(f"Error in send_proposal_reminder_job({appointment_id}): {e}")
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
        staff_repo = StaffRepository(connection)
        clinic_repo = ClinicRepository(connection)
        appointment_management = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)
        notification_service = AppointmentNotificationService(bot, user_repo, appointment_repo)

        await complete_appointment(appointment_management, notification_service, appointment_id)

    except AppointmentNotFoundError:
        logger.warning(f"Mark completion job: appointment {appointment_id} not found")
    except Exception as e:
        logger.exception(
            f"Error in mark_appointment_completed_job({appointment_id}): {e}"
        )
    finally:
        if connection is not None:
            await connection.close()


async def auto_complete_appointment_job(appointment_id: int) -> None:
    """Silently complete a CONFIRMED appointment 2 hours after its datetime.

    This job is called by APScheduler 2 hours after the appointment datetime.
    Re-checks the appointment's live status before acting: only completes it if
    it is still CONFIRMED with no active reschedule negotiation
    (proposed_datetime is None). No notification is sent - this mirrors the
    effect of the admin pressing "skip" on the T+1h completion-followup prompt.

    Args:
        appointment_id: The ID of the appointment to auto-complete
    """
    connection = None
    try:
        config = load_config()

        db = Database(config.database_path)
        connection = await db.connect()

        appointment_repo = AppointmentRepository(connection)
        user_repo = UserRepository(connection)
        staff_repo = StaffRepository(connection)
        clinic_repo = ClinicRepository(connection)
        appointment_management = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

        appointment = await appointment_management.complete_confirmed_appointment(appointment_id)

        if appointment is None:
            logger.info(
                f"Auto-complete job: appointment {appointment_id} not eligible "
                f"(not found / not CONFIRMED / negotiation in progress)"
            )
            return

        logger.info(f"Appointment {appointment_id} auto-completed (2h after appointment)")

    except AppointmentNotFoundError:
        logger.warning(f"Auto-complete job: appointment {appointment_id} not found")
    except Exception as e:
        logger.exception(f"Error in auto_complete_appointment_job({appointment_id}): {e}")
    finally:
        if connection is not None:
            await connection.close()


async def auto_confirm_pending_job(appointment_id: int) -> None:
    """[LEGACY] Auto-confirm PENDING appointment 2 hours before it starts.

    This job is called by APScheduler 2 hours before the appointment datetime.
    Previously transitioned PENDING → CONFIRMED to default an unanswered
    admin-created appointment. This function is kept for backward compatibility
    with existing jobs persisted to the job store, but is no longer scheduled
    for new appointments — both CLIENT and ADMIN-created appointments now
    expire via expire_pending_request_job if unanswered.

    Fires 2h before (after the 2h reminder is sent, but before the
    1h cancellation cutoff window closes).

    Args:
        appointment_id: The ID of the appointment to auto-confirm
    """
    connection = None
    try:
        bot = get_bot()
        config = load_config()

        db = Database(config.database_path)
        connection = await db.connect()

        appointment_repo = AppointmentRepository(connection)
        user_repo = UserRepository(connection)
        staff_repo = StaffRepository(connection)
        clinic_repo = ClinicRepository(connection)
        appointment_management = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

        appointment = await appointment_management.auto_confirm_pending(appointment_id)

        if appointment is None:
            logger.warning(f"Auto-confirm job: appointment {appointment_id} not found or not eligible")
            return

        logger.info(f"Appointment {appointment_id} auto-confirmed (2h before)")

        # Notify client about auto-confirmation
        notification_service = AppointmentNotificationService(bot, user_repo, appointment_repo)

        try:
            notification_sent = await notification_service.notify_client_auto_confirmed(appointment)
            if notification_sent:
                logger.info(f"Auto-confirm notification sent to client for appointment {appointment_id}")
            else:
                logger.warning(
                    f"Failed to send auto-confirm notification for appointment {appointment_id} "
                    f"(client not found or no telegram_id)"
                )
        except Exception as e:
            logger.warning(
                f"Failed to send auto-confirm notification for appointment {appointment_id}: {e}"
            )

    except AppointmentNotFoundError:
        logger.warning(f"Auto-confirm job: appointment {appointment_id} not found")
    except Exception as e:
        logger.exception(f"Error in auto_confirm_pending_job({appointment_id}): {e}")
    finally:
        if connection is not None:
            await connection.close()
