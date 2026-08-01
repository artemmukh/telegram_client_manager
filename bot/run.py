import asyncio
import logging

from aiogram.types import BotCommandScopeDefault

from bot.config.booking_config import MAX_BOOKINGS_PER_SLOT
from bot.handlers.client.geolocation import create_price_geo_router
from bot.handlers.client.price_list import create_price_list_router
from bot.loader import get_bot, get_notifier
from bot.create_bot import dp, db, config

bot = get_bot()
from bot.handlers.admin.client_management.client_creation import create_admin_client_creation_router
from bot.handlers.admin.client_management.client_menu import create_admin_client_menu_router
from bot.handlers.admin.client_management.client_browser import create_admin_client_browser_router
from bot.handlers.admin.client_management.name_change_approval import create_admin_name_change_router
from bot.handlers.admin.appointment_management.record_menu import create_admin_record_router
from bot.handlers.admin.appointment_management.appointment_completion import create_admin_completion_router
from bot.handlers.admin.appointment_management.appointment_creation import create_admin_appointment_creation_router
from bot.handlers.admin.appointment_management.appointment_browser import create_admin_appointment_browser_router
from bot.handlers.admin.appointment_management.booking_requests import create_admin_booking_requests_router
from bot.handlers.admin.appointment_management.reschedule_requests import create_admin_reschedule_requests_router
from bot.handlers.client.appointment_booking import create_client_booking_router
from bot.handlers.client.appointment_invite import create_client_appointment_invite_router
from bot.handlers.client.appointment_reschedule import create_client_reschedule_router
from bot.handlers.client.appointment_response import create_client_appointment_router
from bot.handlers.client.name_change_request import create_name_change_request_router
from bot.handlers.common.help import create_help_router
from bot.handlers.common.personal_data import create_personal_data_router
from bot.handlers.common.profile import create_profile_router
from bot.handlers.common.start import create_start_router
from bot.handlers.registration import create_reg_router
from bot.keyboards.common.profile_kb import personal_data_broadcast_kb
from bot.middlewares.error import ErrorMiddleware
from bot.middlewares.logging import LoggingMiddleware
from bot.middlewares.user import UserContextMiddleware
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.medical_record_repository import MedicalRecordRepository
from bot.repositories.user_repository import UserRepository
from bot.repositories.staff_repository import StaffRepository
from bot.repositories.client_clinic_repository import ClientClinicRepository
from bot.repositories.user_settings_repository import UserSettingsRepository
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import AppointmentNotificationService
from bot.services.appointment.appointment_pagination_service import AppointmentPaginationService
from bot.services.appointment.appointment_scheduler import AppointmentScheduler
from bot.services.client.client_management import ClientManagement
from bot.services.client.client_notifications import ClientNotificationService
from bot.services.llm.agent import ChatLLM
from bot.services.medical_record.medical_record_management import MedicalRecordService
from bot.utils.commands import DEFAULT_COMMANDS

logger = logging.getLogger(__name__)


async def main():

    connection = await db.connect()

    user_repo = UserRepository(connection)
    appointment_repo = AppointmentRepository(connection)
    clinic_repo = ClinicRepository(connection)
    staff_repo = StaffRepository(connection)
    client_clinic_repo = ClientClinicRepository(connection)
    medical_record_repo = MedicalRecordRepository(connection)

    await user_repo.init()

    user_settings_repo = UserSettingsRepository(connection)
    await user_settings_repo.init()

    await appointment_repo.init(MAX_BOOKINGS_PER_SLOT)
    await medical_record_repo.init()
    await clinic_repo.init(config.instance)
    await staff_repo.init(config.instance)
    await client_clinic_repo.init()

    dp["user_repo"] = user_repo  # makes user_repo injectable into filters/handlers
    dp["appointment_repo"] = appointment_repo

    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())

    dp.message.middleware(ErrorMiddleware())
    dp.callback_query.middleware(ErrorMiddleware())

    dp.message.middleware(UserContextMiddleware(user_repo))
    dp.callback_query.middleware(UserContextMiddleware(user_repo))

    # Create services
    client_management_service = ClientManagement(
        user_repo, staff_repo, clinic_repo, client_clinic_repository=client_clinic_repo,
        user_settings_repository=user_settings_repo,
    )
    appointment_management_service = AppointmentManagement(
        appointment_repo, user_repo, staff_repo, clinic_repo,
        client_clinic_repository=client_clinic_repo,
    )
    notifier = get_notifier()
    notification_service = AppointmentNotificationService(notifier, user_repo, appointment_repo)
    client_notification_service = ClientNotificationService(notifier, user_repo)
    appointment_pagination_service = AppointmentPaginationService(appointment_repo)
    chat_llm = ChatLLM(config.mistral_api_key, config.mistral_model)
    medical_record_service = MedicalRecordService(
        medical_record_repo, appointment_management_service, chat_llm, instance=config.instance,
    )

    # Create and start scheduler for appointment reminders
    scheduler = dp["scheduler"]
    scheduler.start()

    # Verify persistent jobs loaded
    loaded_jobs = scheduler.get_jobs()
    logger.info(f"Loaded {len(loaded_jobs)} jobs from persistent store")

    appointment_scheduler = AppointmentScheduler(
        scheduler=scheduler,
        notification_service=notification_service,
        appointment_management=appointment_management_service,
    )

    # Routers

    #registration
    dp.include_router(create_reg_router(
        user_repo, clinic_repo, staff_repo, client_notification_service, client_clinic_repo,
    ))

    #common handlers
    dp.include_router(create_start_router())
    dp.include_router(create_help_router())
    dp.include_router(create_profile_router(client_management_service))
    dp.include_router(create_personal_data_router(client_management_service))
    dp.include_router(create_name_change_request_router(client_management_service, client_notification_service))

    #admin handlers

    #main admin menu
    dp.include_router(create_admin_client_menu_router())

    #create
    dp.include_router(create_admin_client_creation_router(user_repo, staff_repo, clinic_repo, client_clinic_repo))

    #browse (view/edit/delete)
    dp.include_router(create_admin_client_browser_router(
        user_repo, staff_repo, clinic_repo, appointment_repo, client_clinic_repo, instance=config.instance,
    ))

    #name-change approval
    dp.include_router(create_admin_name_change_router(user_repo, staff_repo, clinic_repo, client_clinic_repo))

    #record handlers
    dp.include_router(create_admin_record_router(user_repo, staff_repo, clinic_repo, client_clinic_repo))
    dp.include_router(create_admin_appointment_creation_router(
        config.instance, appointment_repo, user_repo, staff_repo, clinic_repo, client_management_service,
        notification_service, appointment_scheduler, client_clinic_repo,
    ))
    # booking_requests and reschedule_requests are registered before
    # appointment_browser: their propose-datetime calendars (choose_day/
    # choose_slot states) must take priority over appointment_browser's own
    # unfiltered ApptCalendarMonthCB/ApptCalendarDayCB handlers while one of
    # those negotiation flows' state is active. See the ordering comments in
    # booking_requests.py/reschedule_requests.py for the matching state-filter
    # half of this fix.
    dp.include_router(create_admin_booking_requests_router(
        config.instance, appointment_repo, user_repo, staff_repo, clinic_repo, notification_service, appointment_scheduler
    ))
    dp.include_router(create_admin_reschedule_requests_router(
        config.instance, appointment_repo, user_repo, staff_repo, clinic_repo, notification_service, appointment_scheduler
    ))
    dp.include_router(create_admin_appointment_browser_router(
        config.instance, appointment_repo, user_repo, staff_repo, clinic_repo, appointment_scheduler, notification_service,
        medical_record_service=medical_record_service,
    ))
    dp.include_router(create_admin_completion_router(
        appointment_repo, user_repo, staff_repo, clinic_repo, appointment_scheduler, notification_service,
    ))

    #client handlers
    dp.include_router(create_client_appointment_router(
        appointment_pagination_service, appointment_management_service, notification_service, appointment_scheduler,
        medical_record_service=medical_record_service,
    ))
    dp.include_router(create_client_booking_router(
        appointment_management_service, notification_service, appointment_scheduler
    ))
    dp.include_router(create_client_reschedule_router(
        appointment_management_service, notification_service, appointment_scheduler
    ))
    dp.include_router(create_client_appointment_invite_router(
        appointment_management_service, notification_service, appointment_scheduler
    ))
    dp.include_router(create_price_list_router(config.instance))
    dp.include_router(create_price_geo_router(config.instance))

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Starting bot with appointment reminders enabled")
        # dp["personal_data_broadcast_task"] = asyncio.create_task(
        #     client_notification_service.broadcast_personal_data_request(personal_data_broadcast_kb())
        # )
        await bot.set_my_commands(DEFAULT_COMMANDS, scope=BotCommandScopeDefault())
        await dp.start_polling(bot)
    finally:
        # Graceful shutdown of scheduler
        scheduler.shutdown()
        await db.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")
