from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.user_exceptions import InvalidPhoneError, InvalidFullNameError
from bot.keyboards.inline_reply_admin_keyboards import client_keyboard, record_keyboard, client_creation_kb, \
    start_admin_keyboard, cancel_kb
from bot.services.client_management import ClientManagement
from bot.states.user_states import ClientStates
from bot.validators.validators import validate_phone, validate_full_name, validate_fields_filled


def create_admin_router(user_repo, record_repo):

    router = Router()

    cl_mng = ClientManagement(user_repo)

    @router.message(F.text.in_({"/client_managing", "👤 Управление клиентами"}))
    async def client_managing(message: Message):
        await message.answer(text="Выберите действие над клиентом:", reply_markup=client_keyboard())






    @router.callback_query(F.data == "create_client")
    async def create_client_name(callback_query: CallbackQuery, state: FSMContext):
        await state.set_state(ClientStates.client_full_name)
        await callback_query.answer('')
        await callback_query.message.edit_text(text="Введите ФИО:", reply_markup=cancel_kb())



    @router.message(ClientStates.client_full_name)
    async def create_client_phone(message: Message, state: FSMContext):
        client_full_name = message.text.strip()
        try:
            validate_full_name(client_full_name)
        except InvalidFullNameError as e:
            await message.answer(str(e))
            return

        await state.update_data(full_name=client_full_name)
        await state.set_state(ClientStates.client_phone)

        await message.answer(text="Введите номер телефона:", reply_markup=cancel_kb())

    @router.message(ClientStates.client_phone)
    async def process_client_phone(message: Message, state: FSMContext):

        client_phone = message.text.strip()
        try:
            validate_phone(client_phone)
        except InvalidPhoneError as e:
            await message.answer(str(e))
            return

        await state.update_data(phone=client_phone)

        data = await state.get_data()
        await message.answer(
            text=(
                "Проверьте данные клиента:\n\n"
                f"ФИО: {data['full_name']}\n"
                f"Телефон: {data['phone']}\n\n"
                "Нажмите «Завершить» для подтверждения."
            ),
            reply_markup=client_creation_kb()
        )





    @router.callback_query(F.data == "client_creation_finish")
    async def client_creation_finish(callback_query: CallbackQuery, state: FSMContext):


        data = await state.get_data()

        await validate_fields_filled(data, callback_query)


        await cl_mng.create_client(data)

        await callback_query.answer('')
        await callback_query.message.edit_text(
            text=f"Клиент {data['full_name']},\n"
                 f"Номер: {data['phone']}\n добавлен успешно!"
        )

        await state.clear()



    @router.callback_query(F.data == "client_creation_edit_full_name")
    async def edit_name(callback: CallbackQuery, state: FSMContext):

        await state.set_state(ClientStates.client_full_name)

        await callback.answer('')

        await callback.message.edit_text(
            "Введите ФИО заново:", reply_markup=cancel_kb()
        )



    @router.callback_query(F.data == "client_creation_edit_phone")
    async def edit_phone(callback: CallbackQuery, state: FSMContext):

        await state.set_state(ClientStates.client_phone)

        await callback.answer('')

        await callback.message.edit_text(
            "Введите телефон заново:", reply_markup=cancel_kb())



    








    async def delete_client(message: Message):
        pass

    async def search_client(message: Message):
        pass

    async def update_client(message: Message):
        pass

    @router.callback_query(F.data == "back_to_main_clients")
    async def back_to_main(callback_query: CallbackQuery):
        await callback_query.message.edit_text(text="Выберите действие над клиентом:", reply_markup=client_keyboard())






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