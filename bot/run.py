import asyncio
from bot.create_bot import bot, dp, db
from bot.handlers.admin.client_management.client_creation import create_admin_client_creation_router
from bot.handlers.admin.client_management.client_menu import create_admin_client_menu_router
from bot.handlers.admin.client_management.client_search import create_admin_client_search_router
from bot.handlers.admin.client_management.client_delete import create_admin_client_deletion_router
from bot.handlers.admin.client_management.client_update import create_admin_client_update_router
from bot.handlers.admin.record_management.record_menu import create_admin_record_router
from bot.handlers.common.cancel import create_cancel_router
from bot.handlers.common.help import create_help_router
from bot.handlers.common.profile import create_profile_router
from bot.handlers.common.start import create_start_router
from bot.handlers.registration import create_reg_router
from bot.middlewares.user import UserContextMiddleware
from bot.repositories.records_repository import RecordRepository
from bot.repositories.user_repository import UserRepository


async def main():

    connection = await db.connect()

    user_repo = UserRepository(connection)
    record_repo = RecordRepository(connection)

    await user_repo.init()
    await record_repo.init()

    dp["user_repo"] = user_repo  # makes user_repo injectable into filters/handlers
    dp["record_repo"] = record_repo

    dp.message.middleware(UserContextMiddleware(user_repo))
    dp.callback_query.middleware(UserContextMiddleware(user_repo))

    # Routers

    #registration
    dp.include_router(create_reg_router(user_repo))

    #common handlers
    dp.include_router(create_start_router())
    dp.include_router(create_help_router())
    dp.include_router(create_cancel_router())
    dp.include_router(create_profile_router())

    #admin handlers

    #main admin menu
    dp.include_router(create_admin_client_menu_router())

    #create
    dp.include_router(create_admin_client_creation_router(user_repo))

    #search
    dp.include_router(create_admin_client_search_router(user_repo))

    #delete
    dp.include_router(create_admin_client_deletion_router(user_repo))

    #update
    dp.include_router(create_admin_client_update_router(user_repo))

    #record handlers
    dp.include_router(create_admin_record_router(record_repo))

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")