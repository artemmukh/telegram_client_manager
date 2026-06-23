from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from bot.keyboards.inline_keyboards import start_keyboard, client_keyboard, record_keyboard, contact_keyboard


def create_router() -> Router:
    router = Router()


    @router.message(F.text == "/start")
    async def start(message: Message):
        # await message.answer(
        #     "Отправь номер телефона для регистрации:",
        #     reply_markup=contact_keyboard())
        await message.answer(f"Здравствуйте {message.from_user.first_name}.\n\n"
                             "Это бот для учета клиентов. С помощью ручного или голосового ввода с ИИ расшифровкой ведется учет клиентской базы.\n\n"
                             'Для ознакомления с функционалом нажмите "Справка".')
        await message.answer(text='Выберите вариант: ', reply_markup=start_keyboard())


#displaying identical help for both command and button
    @router.message(F.text.in_({"/help", "❓ Справка"}))
    async def get_help(message: Message):
        text = ("Справочное меню.\n\n\n"
                "/client_managing:\n\n"
                "  1. Создание нового клиента.\n"
                "  2. Удаление клиента.\n"
                "  3. Поиск клиента.\n"
                "  4. Обновления данных клиента.\n\n\n"
                "/record_managing:\n\n"
                "1. Создать запись клиента.\n"
                "2. Удалить запись клиента.\n"
                "3. Поиск записи клиента.\n"
                "4. Изменить запись клиента.\n\n\n"
                "/start - запуск бота.\n"
                "/help - справка.\n"
                "/profile - личные данные.")
        await message.answer(text=text, reply_markup=start_keyboard())



    @router.message(F.text.in_({"/client_managing", "👤 Управление клиентами"}))
    async def client_managing(message: Message):
        await message.answer(text="Выберите действие:" , reply_markup=client_keyboard())

    @router.message(Command("create_client"))
    async def create_client(message: Message):
        pass

    @router.message(Command("delete_client"))
    async def delete_client(message: Message):
        pass

    @router.message(Command("search_client"))
    async def search_client(message: Message):
        pass

    @router.message(Command("update_client"))
    async def update_client(message: Message):
        pass


    @router.message(F.text.in_({"/record_managing", "📒 Управление записями"}))
    async def record_managing(message: Message):
        await message.answer(text="Выберите действие:", reply_markup=record_keyboard())

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


    @router.message(F.text.in_({"/profile", "⚙️ Мой профиль"}))
    async def profile(message: Message):

        await message.answer(f"Профиль\n\n"
                             f"Имя: {message.from_user.first_name}\n"
                             f"ID: {message.from_user.id}\n"
                             f"Username: @{message.from_user.username}"
                             f"Тип пользователя:")
    return router

