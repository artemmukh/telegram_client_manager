import asyncio

from bot.create_bot import bot, dp, db_path
from bot.handlers.admin.client_management.client_creation import create_admin_client_creation_router
from bot.handlers.admin.client_management.client_menu import create_admin_client_menu_router
from bot.handlers.admin.record_management.record_menu import create_admin_record_router
from bot.handlers.main_handler import create_main_router
from bot.repositories.records_repository import RecordRepository
from bot.repositories.user_repository import UserRepository


async def main():



    user_repo = UserRepository(db_path)
    record_repo = RecordRepository(db_path)

    await user_repo.init()
    await record_repo.init()

    dp["user_repo"] = user_repo  # makes user_repo injectable into filters/handlers
    dp["record_repo"] = record_repo

    dp.include_router(create_main_router(user_repo))
    dp.include_router(create_admin_client_menu_router())
    dp.include_router(create_admin_client_creation_router(user_repo))
    dp.include_router(create_admin_record_router(record_repo))



    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")