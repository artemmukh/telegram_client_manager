
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import InvalidPhoneError, InvalidFullNameError, PhoneAlreadyExistsError, \
    ValidationError
from bot.handlers.utils.admin_utils.confirmations import build_client_text, show_success, show_confirmation
from bot.handlers.utils.admin_utils.input_helpers import (
    edit_full_name,
    edit_phone, ask_full_name, full_name_processing, phone_processing
)
from bot.keyboards.admin.client_management_kb.client_creation_kb import (
    client_creation_back_kb,
    client_creation_duplicate_name_kb,
    client_creation_kb,
)
from bot.services.client.client_management import ClientManagement
from bot.states.admin.client_management.client_creation_states import ClientCreationStates
from bot.utils.role import RoleFilter
from bot.validators.validators import SEARCH_NAME_PATTERN
from bot.validators.validators import validate_fields_filled


def create_admin_client_creation_router(user_repo, staff_repo, clinic_repo):

    router = Router()

    cl_mng = ClientManagement(user_repo, staff_repo, clinic_repo)

    async def validate_phone_available(phone: str):
        if await cl_mng.is_phone_taken(phone):
            raise PhoneAlreadyExistsError("Номер уже зарегистрирован. Пожалуйста, введите другой:")


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
        await ask_full_name(
            callback_query, state,
            next_state=ClientCreationStates.client_full_name,
            reply_markup=client_creation_back_kb(),
        )

    @router.message(ClientCreationStates.client_full_name, F.text)
    async def create_client_phone(message: Message, state: FSMContext):
       if not await full_name_processing(message, state, next_state=ClientCreationStates.client_phone, re_pattern=SEARCH_NAME_PATTERN):
           return
       await message.answer(text="Введите номер телефона:", reply_markup=client_creation_back_kb())

    @router.message(ClientCreationStates.client_phone, F.text)
    async def confirm(message: Message, state: FSMContext):
        if not await phone_processing(
                message,
                state,
                validator=validate_phone_available,
                final_state=ClientCreationStates.confirm_create
        ):
            return
        await show_confirmation(message, state, reply_markup=client_creation_kb())

    @router.callback_query(
        ClientCreationStates.confirm_create,
        F.data == "client_creation_edit_full_name"
    )
    async def full_name_edition(callback: CallbackQuery, state: FSMContext):
        await edit_full_name(
            callback, state,
            edit_state=ClientCreationStates.edit_full_name,
            reply_markup=client_creation_back_kb(),
        )

    @router.message(ClientCreationStates.edit_full_name, F.text)
    async def process_full_name_edition(message: Message, state: FSMContext):
        if not await full_name_processing(
            message, state,
            next_state=ClientCreationStates.confirm_create, re_pattern=SEARCH_NAME_PATTERN
        ):
            return
        await show_confirmation(message, state, reply_markup=client_creation_kb())

    @router.callback_query(
        ClientCreationStates.confirm_create,
        F.data == "client_creation_edit_phone"
    )
    async def phone_edition(callback: CallbackQuery, state: FSMContext):
        await edit_phone(
            callback, state,
            edit_state=ClientCreationStates.edit_phone,
            reply_markup=client_creation_back_kb(),
        )

    @router.message(ClientCreationStates.edit_phone, F.text)
    async def process_phone_edition(message: Message, state: FSMContext):
        if not await phone_processing(message,
                state,
                validator=validate_phone_available,
                final_state=ClientCreationStates.confirm_create
        ):
            return
        await show_confirmation(message, state, reply_markup=client_creation_kb())


    async def _finalize_client_creation(callback_query: CallbackQuery, state: FSMContext, data: dict) -> None:
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

    @router.callback_query(F.data == "client_creation_finish")
    async def client_creation_finish(callback_query: CallbackQuery, state: FSMContext):

        data = await state.get_data()

        try:
            validate_fields_filled(data)
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        duplicates = await cl_mng.find_clients_by_exact_name(data['full_name'], data['clinic_id'])
        if duplicates:
            if len(duplicates) == 1:
                text = (
                    f"Клиент с именем {data['full_name']} уже существует "
                    f"(телефон: {duplicates[0].phone}). Продолжить создание?"
                )
            else:
                text = (
                    f"Клиенты с именем {data['full_name']} уже существуют "
                    f"({len(duplicates)} чел., например телефон: {duplicates[0].phone}). Продолжить создание?"
                )
            await state.set_state(ClientCreationStates.confirm_duplicate_name)
            await callback_query.message.edit_text(text, reply_markup=client_creation_duplicate_name_kb())
            await callback_query.answer('')
            return

        await _finalize_client_creation(callback_query, state, data)

    @router.callback_query(ClientCreationStates.confirm_duplicate_name, F.data == "client_creation_duplicate_confirm")
    async def client_creation_duplicate_confirm(callback_query: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        await _finalize_client_creation(callback_query, state, data)

    @router.callback_query(ClientCreationStates.confirm_duplicate_name, F.data == "client_creation_duplicate_cancel")
    async def client_creation_duplicate_cancel(callback_query: CallbackQuery, state: FSMContext):
        await state.set_state(ClientCreationStates.confirm_create)
        data = await state.get_data()
        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_client_text("Проверьте введенные данные:", data),
            reply_markup=client_creation_kb(),
        )


    return router
