from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import InvalidPhoneError, InvalidFullNameError, PhoneAlreadyExistsError, \
    ValidationError
from bot.handlers.utils.utils import show_confirmation, show_creation_success
from bot.keyboards.admin.client_management_kb.client_creation_kb import client_creation_kb
from bot.keyboards.utils.utils_kb import cancel_kb
from bot.services.client.client_management import ClientManagement
from bot.states.admin.client_management.client_creation_states import ClientCreationStates
from bot.states.utils.client_edit_states import EditStates
from bot.validators.validators import validate_phone, validate_full_name, validate_fields_filled, \
    validate_phone_available


def create_admin_client_creation_router(user_repo):

    router = Router()

    cl_mng = ClientManagement(user_repo)


    @router.callback_query(F.data == "create_client")
    async def create_client_name(callback_query: CallbackQuery, state: FSMContext):
        await state.set_state(ClientCreationStates.client_full_name)
        await callback_query.answer('')
        await callback_query.message.edit_text(text="Введите ФИО:", reply_markup=cancel_kb())





    @router.message(ClientCreationStates.client_full_name, F.text)
    async def create_client_phone(message: Message, state: FSMContext):
        client_full_name = message.text.strip()

        try:

            validate_full_name(client_full_name)
        except InvalidFullNameError as e:
            await message.answer(str(e))
            return

        await state.update_data(full_name=client_full_name)
        await state.set_state(ClientCreationStates.client_phone)

        await message.answer(text="Введите номер телефона:", reply_markup=cancel_kb())





    @router.message(ClientCreationStates.client_phone, F.text)
    async def process_client_phone(message: Message, state: FSMContext):

        try:
            client_phone = validate_phone(message.text.strip())
            await validate_phone_available(user_repo, client_phone)
        except InvalidPhoneError as e:
            await message.answer(str(e))
            return
        except PhoneAlreadyExistsError as e:
            await message.answer(str(e))
            return

        await state.update_data(phone=client_phone)

        await state.set_state(ClientCreationStates.confirm_create)

        await show_confirmation(message, state, client_creation_kb())







    @router.callback_query(
        ClientCreationStates.confirm_create,
        F.data == "client_creation_edit_full_name"
    )
    async def edit_name(callback: CallbackQuery, state: FSMContext):

        await state.set_state(EditStates.edit_full_name)

        await callback.answer('')

        await callback.message.edit_text(
            "Введите новое ФИО:",
            reply_markup=cancel_kb()
        )








    @router.message(EditStates.edit_full_name, F.text)
    async def process_edit_name(message: Message, state: FSMContext):

        client_full_name = message.text.strip()

        try:
            validate_full_name(client_full_name)
        except InvalidFullNameError as e:
            await message.answer(str(e))
            return

        await state.update_data(full_name=client_full_name)

        await state.set_state(ClientCreationStates.confirm_create)

        await show_confirmation(message, state, client_creation_kb())





    @router.callback_query(
        ClientCreationStates.confirm_create,
        F.data == "client_creation_edit_phone"
    )
    async def edit_phone(callback: CallbackQuery, state: FSMContext):

        await state.set_state(EditStates.edit_phone)


        await callback.answer('')

        await callback.message.edit_text(
            "Введите новый телефон:",
            reply_markup=cancel_kb()
        )





    @router.message(EditStates.edit_phone, F.text)
    async def process_edit_phone(message: Message, state: FSMContext):


        try:
            client_phone = validate_phone(message.text.strip())
            await validate_phone_available(user_repo, client_phone)
        except InvalidPhoneError as e:
            await message.answer(str(e))
            return
        except PhoneAlreadyExistsError as e:
            await message.answer(str(e))
            return

        await state.update_data(phone=client_phone)

        await state.set_state(ClientCreationStates.confirm_create)

        await show_confirmation(message, state, client_creation_kb())


    @router.callback_query(F.data == "client_creation_finish")
    async def client_creation_finish(callback_query: CallbackQuery, state: FSMContext):

        data = await state.get_data()

        try:
            validate_fields_filled(data)
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        try:
            await cl_mng.create_client(data)
        except (InvalidPhoneError, InvalidFullNameError) as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка создания клиента: {e}", show_alert=True)
            return


        await show_creation_success(state, callback_query)

        await state.clear()


    return router

