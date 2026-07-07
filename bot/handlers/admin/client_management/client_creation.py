
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import InvalidPhoneError, InvalidFullNameError, PhoneAlreadyExistsError, ValidationError
from bot.handlers.utils.admin_utils.confirmations import show_success, show_confirmation
from bot.handlers.utils.admin_utils.input_helpers import (
    edit_full_name,
    edit_phone,
    process_edit_full_name,
    process_edit_phone, ask_full_name, full_name_processing, phone_processing
)
from bot.utils.role import RoleFilter
from bot.validators.validators import FULL_NAME_PATTERN
from bot.keyboards.admin.client_management_kb.client_creation_kb import client_creation_kb
from bot.keyboards.utils.utils_kb import cancel_kb
from bot.services.client.client_management import ClientManagement
from bot.states.admin.client_management.client_creation_states import ClientCreationStates
from bot.validators.validators import validate_fields_filled, validate_phone_available


def create_admin_client_creation_router(user_repo, staff_repo, clinic_repo):

    router = Router()

    cl_mng = ClientManagement(user_repo, staff_repo, clinic_repo)


    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))


    @router.callback_query(F.data == "create_client")
    async def create_client_name(callback_query: CallbackQuery, state: FSMContext):
        try:
            clinic = await cl_mng.get_admin_clinic(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        await state.update_data(clinic_id=clinic.clinic_id, clinic_name=clinic.name)
        await ask_full_name(callback_query, state, next_state=ClientCreationStates.client_full_name)

    @router.message(ClientCreationStates.client_full_name, F.text)
    async def create_client_phone(message: Message, state: FSMContext):
       if not await full_name_processing(message, state, next_state=ClientCreationStates.client_phone, re_pattern=FULL_NAME_PATTERN):
           return
       await message.answer(text="Введите номер телефона:", reply_markup=cancel_kb())

    @router.message(ClientCreationStates.client_phone, F.text)
    async def confirm(message: Message, state: FSMContext):
        if not await phone_processing(
                message,
                state,
                validator=lambda phone: validate_phone_available(user_repo, phone),final_state=ClientCreationStates.confirm_create
        ):
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
            final_state=ClientCreationStates.confirm_create, re_pattern=FULL_NAME_PATTERN
        ):
            return
        await show_confirmation(message, state, reply_markup=client_creation_kb())

    @router.callback_query(
        ClientCreationStates.confirm_create,
        F.data == "client_creation_edit_phone"
    )
    async def phone_edition(callback: CallbackQuery, state: FSMContext):
        await edit_phone(callback, state, edit_state=ClientCreationStates.edit_phone)

    @router.message(ClientCreationStates.edit_phone, F.text)
    async def process_phone_edition(message: Message, state: FSMContext):
        if not await process_edit_phone(message,
                state,
                validator=lambda phone: validate_phone_available(user_repo, phone),final_state=ClientCreationStates.confirm_create
        ):
            return
        await show_confirmation(message, state, reply_markup=client_creation_kb())


    @router.callback_query(F.data == "client_creation_finish")
    async def client_creation_finish(callback_query: CallbackQuery, state: FSMContext):

        data = await state.get_data()

        try:
            validate_fields_filled(data)
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        try:
            user = await cl_mng.create_client(callback_query.from_user.id, data)
        except PhoneAlreadyExistsError:
            await state.clear()
            await callback_query.message.edit_text(
                "Пациент с таким номером телефона уже существует.",
                reply_markup=None,
            )
            await callback_query.answer('')
            return
        except (InvalidPhoneError, InvalidFullNameError) as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка создания клиента: {e}", show_alert=True)
            return

        await show_success(
            callback_query,
            "Клиент успешно добавлен!",
            full_name=user.full_name,
            phone=user.phone,
            clinic_name=user.clinic_name,
        )

        await state.clear()


    return router
