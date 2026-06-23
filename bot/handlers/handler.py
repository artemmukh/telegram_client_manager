from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from bot.states.client_states import ClientStates
from bot.keyboards.inline_keyboards import start_keyboard


def createRouter() -> Router:
    router = Router()


    @router.message(F.text == "/start")
    async def start(message: Message):
        await message.answer(f"Здравствуйте {message.from_user.first_name}.\n\n"
                             "Это бот для учета клиентов. С помощью ручного или голосового ввода с ИИ расшифровкой ведется учет клиентской базы.\n\n"
                             'Для ознакомления с функционалом нажмите "Справка".')
        builder = start_keyboard()
        await message.answer(text='Выберите вариант: ', reply_markup=builder)

    @router.message(F.text == "/help")
    async def help(message: Message):
        await message.answer("Справочное меню.\n\n\n"
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
                             "/help - справка.")

    @router.message(Command("create_client"))
    async def create_client(message: Message, state: FSMContext):
        await message.answer("Введите Фамилию и Имя:")
        await state.set_state(ClientStates.client_name)

    @router.message(ClientStates.client_name)
    async def client_name_handler(message: Message, state: FSMContext):
        await state.update_data(name=message.text)
        await message.answer("Введите номер телефона (н.п) 901234567):")
        await state.set_state(ClientStates.client_phone)

    @router.message(ClientStates.client_phone)
    async def client_phone_handler(message: Message, state: FSMContext):
        await state.update_data(phone=message.text)
        await state.set_state()

    @router.message(ClientStates.client_name, )



    @router.message(Command("delete_client"))
    async def delete_client(message: Message):
        pass

    @router.message(Command("search_client"))
    async def search_client(message: Message):
        pass

    @router.message(Command("update_client"))
    async def update_client(message: Message):
        pass

    @router.message(Command("create_record"))
    async def create_record(message: Message):
        pass

    @router.message(Command("delete_record"))
    async def delete_record(message: Message):
        pass

    @router.message(Command("search_record"))
    async def search_record(message: Message):
        pass

    @router.message(Command("update_record"))
    async def update_record(message: Message):
        pass


    return router

