
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import InvalidPhoneError, InvalidFullNameError, ValidationError
from bot.handlers.utils.admin_utils.confirmations import show_success, show_confirmation
from bot.handlers.utils.admin_utils.input_helpers import (
    edit_full_name,
    edit_phone,
    process_edit_full_name,
    process_edit_phone, ask_full_name, full_name_processing, phone_processing
)
from bot.keyboards.admin.client_management_kb.client_creation_kb import client_creation_kb
from bot.keyboards.utils.utils_kb import cancel_kb
from bot.services.client.client_management import ClientManagement
from bot.states.admin.client_management.client_creation_states import ClientCreationStates
from bot.validators.validators import validate_fields_filled


def create_admin_client_creation_router(user_repo):

    router = Router()

    cl_mng = ClientManagement(user_repo)

    @router.callback_query(F.data == "create_client")
    async def create_client_name(callback_query: CallbackQuery, state: FSMContext):
        await ask_full_name(callback_query, state, next_state=ClientCreationStates.client_full_name)

    @router.message(ClientCreationStates.client_full_name, F.text)
    async def create_client_phone(message: Message, state: FSMContext):
       if not await full_name_processing(message, state, next_state=ClientCreationStates.client_phone):
           return
       await message.answer(text="Введите номер телефона:", reply_markup=cancel_kb())

    @router.message(ClientCreationStates.client_phone, F.text)
    async def confirm(message: Message, state: FSMContext):
        if not await phone_processing(message, state, next_state=ClientCreationStates.confirm_create):
            return
        await show_confirmation(message, state, reply_markup=client_creation_kb())

    @router.callback_query(
        ClientCreationStates.confirm_create,
        F.data == "client_creation_edit_full_name"
    )
    async def full_name_edition(callback: CallbackQuery, state: FSMContext):
        await edit_full_name(callback, state, edit_state=ClientCreationStates.edit_full_name)

    @router.message(ClientCreationStates.edit_full_name, F.text)
    async def process_full_name_edition(message: Message, state: FSMContext):
        if not await process_edit_full_name(
            message, state,
            final_state=ClientCreationStates.confirm_create,
            reply_markup=client_creation_kb(),
        ):
            return

    @router.callback_query(
        ClientCreationStates.confirm_create,
        F.data == "client_creation_edit_phone"
    )
    async def phone_edition(callback: CallbackQuery, state: FSMContext):
        await edit_phone(callback, state, edit_state=ClientCreationStates.edit_phone)

    @router.message(ClientCreationStates.edit_phone, F.text)
    async def process_phone_edition(message: Message, state: FSMContext):
        if not await process_edit_phone(
            message, state,
            final_state=ClientCreationStates.confirm_create,
            reply_markup=client_creation_kb(),
        ):
            return


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

        await show_success(
            callback_query,
            "Клиент успешно добавлен!",
            full_name=data["full_name"],
            phone=data["phone"],
        )

        await state.clear()

    return router
