from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from bot.keyboards.inline_reply_admin_keyboards import client_keyboard, record_keyboard


def create_admin_router(user_repo, record_repo):

    router = Router()

    @router.message(F.text.in_({"/client_managing", "👤 Управление клиентами"}))
    async def client_managing(message: Message):
        await message.answer(text="Выберите действие над клиентом:", reply_markup=client_keyboard())

    @router.callback_query(F.data == "create_client")
    async def create_client(message: Message):
        await message.edit_text(text="Введите ФИО")

    async def delete_client(message: Message):
        pass

    async def search_client(message: Message):
        pass

    async def update_client(message: Message):
        pass




    @router.message(F.text.in_({"/record_managing", "📒 Управление записями"}))
    async def record_managing(message: Message):
        await message.answer(text="Выберите действие над записью:", reply_markup=record_keyboard())

    # @router.message(Command("create_record"))
    # async def create_record(message: Message):
    #     pass
    #
    # @router.message(Command("delete_record"))
    # async def delete_record(message: Message):
    #     pass
    #
    # @router.message(Command("search_record"))
    # async def search_record(message: Message):
    #     pass
    #
    # @router.message(Command("update_record"))
    # async def update_record(message: Message):
    #    pass

    @router.callback_query(F.data.in_({"back_to_main_clients", "back_to_main_records"}))
    async def back_to_main(callback_query: CallbackQuery):

        match callback_query.data:
            case "back_to_main_clients":
                await callback_query.message.edit_text(
                    "Выберите действие над клиентом:",
                    reply_markup=client_keyboard()
                )

            case "back_to_main_records":
                await callback_query.message.edit_text(
                    "Выберите действие над записью:",
                    reply_markup=record_keyboard()
                )

    return router