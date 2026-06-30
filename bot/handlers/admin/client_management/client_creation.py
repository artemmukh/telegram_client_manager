from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.user_exceptions import InvalidPhoneError, InvalidFullNameError
from bot.handlers.admin.client_management.utils.utils import show_creation_confirmation, show_creation_success
from bot.keyboards.utils.utils_kb import cancel_kb
from bot.services.admin.client_management import ClientManagement
from bot.states.user_states import ClientStates
from bot.utils.tools import normalize_phone
from bot.validators.validators import validate_phone, validate_full_name, validate_fields_filled


def create_admin_client_creation_router(user_repo):

    router = Router()

    cl_mng = ClientManagement(user_repo)


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

        client_phone = normalize_phone(client_phone)

        await state.update_data(phone=client_phone)

        await state.set_state(ClientStates.confirm_create)

        await show_creation_confirmation(message, state)

    @router.callback_query(F.data == "client_creation_finish")
    async def client_creation_finish(callback_query: CallbackQuery, state: FSMContext):

        data = await state.get_data()

        await validate_fields_filled(data, callback_query)

        await cl_mng.create_client(data)

        await show_creation_success(state, callback_query)

        await state.clear()

    @router.callback_query(
        ClientStates.confirm_create,
        F.data == "client_creation_edit_full_name"
    )
    async def edit_name(callback: CallbackQuery, state: FSMContext):

        await state.set_state(ClientStates.client_edit_full_name)

        await callback.message.edit_text(
            "Введите новое ФИО:",
            reply_markup=cancel_kb()
        )

        await callback.answer()

    @router.message(ClientStates.client_edit_full_name)
    async def process_edit_name(message: Message, state: FSMContext):

        client_full_name = message.text.strip()
        try:
            validate_full_name(client_full_name)
        except InvalidFullNameError as e:
            await message.answer(str(e))
            return

        await state.update_data(full_name=client_full_name)

        await state.set_state(ClientStates.confirm_create)

        await show_creation_confirmation(message, state)

    @router.callback_query(
        ClientStates.confirm_create,
        F.data == "client_creation_edit_phone"
    )
    async def edit_phone(callback: CallbackQuery, state: FSMContext):

        await state.set_state(ClientStates.client_edit_phone)

        await callback.message.edit_text(
            "Введите новый телефон:",
            reply_markup=cancel_kb()
        )

        await callback.answer()

    @router.message(ClientStates.client_edit_phone)
    async def process_edit_phone(message: Message, state: FSMContext):

        client_phone = message.text.strip()
        try:
            validate_phone(client_phone)
        except InvalidPhoneError as e:
            await message.answer(str(e))
            return

        client_phone = normalize_phone(client_phone)

        await state.update_data(phone=client_phone)

        await state.set_state(ClientStates.confirm_create)

        await show_creation_confirmation(message, state)


    return router

