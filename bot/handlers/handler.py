from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.user_exceptions import InvalidFullNameError
from bot.keyboards.inline_keyboards import start_keyboard, client_keyboard, record_keyboard, contact_keyboard
from bot.models.user import User
from bot.models.record import Record
from bot.services.registration import validate_full_name, RegistrationService
from bot.states.client_states import RegisterStates





async def show_main_menu(message: Message):
    await message.answer(f"Здравствуйте {message.from_user.first_name}.\n\n"
                         "Это бот для учета клиентов. С помощью ручного или голосового ввода с ИИ расшифровкой ведется учет клиентской базы.\n\n"
                         'Для ознакомления с функционалом нажмите "Справка".')

    await message.answer(text='Выберите вариант: ', reply_markup=start_keyboard())

def create_router(user_repo, record_repo) -> Router:
    router = Router()


    @router.message(RegisterStates.user_full_name)
    async def first_reg(message: Message, state: FSMContext):
        user_full_name = message.text.strip()

        try:
            validate_full_name(user_full_name)
        except InvalidFullNameError as e:
            await message.answer(str(e))
            return  # stay in RegisterStates.user_full_name, wait for the next input

        await state.update_data(user_full_name=user_full_name)
        await state.set_state(RegisterStates.user_phone)
        await message.answer(
            "Отправьте ваш контакт: ",
            reply_markup=contact_keyboard()
        )

    @router.message(RegisterStates.user_phone, F.contact)
    async def final_reg(message: Message, state: FSMContext):
        await state.update_data(user_phone=message.contact.phone_number)
        data = await state.get_data()

        reg = RegistrationService(user_repo)

        await reg.register(telegram_user_id=message.from_user.id,
                full_name=data["user_full_name"],
                phone=data["user_phone"])

        await message.answer("Регистрация прошла успешна!")
        await show_main_menu(message)
        await state.clear()


    @router.message(F.text == "/start")
    async def start(message: Message, state: FSMContext):

        if await user_repo.user_exists(message.from_user.id):
            await state.clear()
            await show_main_menu(message)

        else:
            await message.answer("Пройдите регистрацию для дальнейшего взаимодействия.")
            await state.set_state(RegisterStates.user_full_name)
            await message.answer("Отправьте ФИО: ")




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
        await message.answer(text="Выберите действие над клиентом:", reply_markup=client_keyboard())

    # @router.message(Command("create_client"))
    # async def create_client(message: Message):
    #     pass
    #
    # @router.message(Command("delete_client"))
    # async def delete_client(message: Message):
    #     pass
    #
    # @router.message(Command("search_client"))
    # async def search_client(message: Message):
    #     pass
    #
    # @router.message(Command("update_client"))
    # async def update_client(message: Message):
    #     pass

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

    @router.message(F.text.in_({"/profile", "⚙️ Мой профиль"}))
    async def profile(message: Message):

        user = await user_repo.get_user_by_telegram_id(message.from_user.id)
        name = user.full_name
        phone = user.phone
        role = user.role
        ID = user.primary_id

        await message.answer(f"Профиль\n\n"
                             f"ФИО: {name}\n"
                             f"ID клиента: {ID}\n"
                             f"Номер телефона: {phone}\n"
                             f"Тип пользователя: {role}")

    return router
