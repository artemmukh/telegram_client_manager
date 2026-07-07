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
from bot.exceptions.appointment_exceptions import AppointmentNotFoundError

logger = logging.getLogger(__name__)


async def send_reminder_job(appointment_id: int) -> None:
    """Send appointment reminder to client if appointment is still pending.

    This job is called by APScheduler at scheduled reminder times (24h and 2h before).

    Args:
        appointment_id: The ID of the appointment to send reminder for
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

        notification_sent = (
            await notification_service.notify_client_appointment(appointment)
        )

        if notification_sent:
            logger.info(
                f"Reminder sent for appointment {appointment_id}"
            )
        else:
            logger.warning(
                f"Failed to send reminder for appointment {appointment_id} "
                f"(client not found or no telegram_id)"
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


async def mark_appointment_completed_job(appointment_id: int) -> None:
    """Mark appointment as completed (called 1 hour after appointment time).

    This job is called by APScheduler 1 hour after the appointment datetime.
    Updates status to COMPLETED if appointment is still PENDING or CONFIRMED.

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
                await notification_service.bot.send_message(
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

    except AppointmentNotFoundError as e:
        logger.warning(f"Mark completion job: appointment {appointment_id} not found")
    except Exception as e:
        logger.exception(
            f"Error in mark_appointment_completed_job({appointment_id}): {e}"
        )
    finally:
        if connection is not None:
            await connection.close()
