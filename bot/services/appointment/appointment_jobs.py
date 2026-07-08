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
from bot.utils.appointment_enums import AppointmentStatus
from bot.exceptions.appointment_exceptions import AppointmentNotFoundError, NotificationDeliveryError

logger = logging.getLogger(__name__)


async def send_reminder_job(appointment_id: int, hours_before: int = 24) -> None:
    """Send appointment reminder to client based on time until appointment.

    This job is called by APScheduler at scheduled reminder times (24h and 2h before).

    Args:
        appointment_id: The ID of the appointment to send reminder for
        hours_before: Hours before appointment (24 or 2)
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

        # Determine reminder type and send to CLIENT
        reminder_type = None
        notification_sent = False

        try:
            if hours_before == 24:
                # 24h reminder: text only, NO buttons
                notification_sent = (
                    await notification_service.notify_client_appointment_without_buttons(appointment)
                )
                reminder_type = "24h (no buttons)"
            elif hours_before == 2:
                # 2h reminder: text WITH buttons
                notification_sent = (
                    await notification_service.notify_client_appointment_with_buttons(appointment)
                )
                reminder_type = "2h (with buttons)"
            else:
                logger.warning(f"Unknown reminder time: {hours_before}h")
                return

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
        if appointment.created_by_telegram_id and client:
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

    except AppointmentNotFoundError as e:
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
    user_repo: UserRepository,
    bot,
    appointment_id: int,
) -> None:
    """Mark appointment as completed and notify the client.

    Shared by the standalone APScheduler job function and by
    AppointmentScheduler (for callers that inject repositories/bot directly,
    e.g. tests).

    Updates status to COMPLETED if appointment is still PENDING or CONFIRMED.

    Args:
        appointment_repo: Repository used to fetch/update the appointment
        user_repo: Repository used to fetch the client
        bot: Bot instance used to notify the client
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
    ):
        logger.info(
            f"Completion job: skipping appointment {appointment_id} "
            f"with status {appointment.status.value}"
        )
        return

    await appointment_repo.update_appointment_status(
        appointment_id,
        AppointmentStatus.COMPLETED
    )

    logger.info(
        f"Appointment {appointment_id} auto-completed"
    )

    try:
        client = await user_repo.get_client_by_id(appointment.client_id)
        if client and client.telegram_user_id:
            await bot.send_message(
                chat_id=client.telegram_user_id,
                text="Ваш прием завершен. Спасибо за посещение!"
            )
            logger.info(
                f"Sent completion notification to client {appointment.client_id}"
            )
    except Exception as e:
        logger.warning(
            f"Failed to send completion notification to client {appointment.client_id}: {e}"
        )


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

        await complete_appointment(appointment_repo, user_repo, bot, appointment_id)

    except AppointmentNotFoundError as e:
        logger.warning(f"Mark completion job: appointment {appointment_id} not found")
    except Exception as e:
        logger.exception(
            f"Error in mark_appointment_completed_job({appointment_id}): {e}"
        )
    finally:
        if connection is not None:
            await connection.close()
