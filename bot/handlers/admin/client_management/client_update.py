from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import InvalidPhoneError, InvalidFullNameError, UserNotFoundError, \
    PhoneAlreadyExistsError, ValidationError, SamePhoneError
from bot.handlers.utils.admin_utils.confirmations import show_success, show_confirmation, show_clients_one_be_one, \
    build_client_text
from bot.handlers.utils.admin_utils.input_helpers import ask_full_name, edit_full_name, phone_processing, \
    full_name_processing, process_edit_full_name, edit_phone, process_edit_phone, ask_phone
from bot.keyboards.admin.client_management_kb.client_update_kb import (
    client_update_kb,
    client_search_to_update_name_kb,
    client_search_to_update_phone_kb,
    choose_to_update_user_kb,
    confirm_new_full_name_kb,
    confirm_new_phone_kb,
)
from bot.services.client.client_management import ClientManagement
from bot.states.admin.client_management.client_update_states import ClientUpdateStates
from bot.utils.role import RoleFilter
from bot.keyboards.utils.utils_kb import cancel_kb
from bot.validators.validators import SEARCH_NAME_PATTERN, FULL_NAME_PATTERN


def create_admin_client_update_router(user_repo, staff_repo, clinic_repo,):
    router = Router()

    cl_mng = ClientManagement(user_repo, staff_repo, clinic_repo,)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    # --- Entry ---

    @router.callback_query(F.data == "update_client")
    async def client_update(callback_query: CallbackQuery):
        await callback_query.answer('')
        await callback_query.message.edit_text(
            text='Выберите метод поиска для изменения:',
            reply_markup=client_update_kb(),
        )

    # --- Search by full name ---

    @router.callback_query(F.data == "client_full_name_update")
    async def client_full_name_search(callback_query: CallbackQuery, state: FSMContext):
        await ask_full_name(callback_query, state, next_state=ClientUpdateStates.client_search_name)

    @router.message(ClientUpdateStates.client_search_name, F.text)
    async def process_client_full_name_search(message: Message, state: FSMContext):
        if not await full_name_processing(
            message, state,
            next_state=ClientUpdateStates.confirm_search,
            re_pattern=SEARCH_NAME_PATTERN,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_search_to_update_name_kb())

    # --- Search by phone ---

    @router.callback_query(F.data == "client_phone_update")
    async def client_phone_search(callback_query: CallbackQuery, state: FSMContext):
        await ask_phone(callback_query, state, ClientUpdateStates.client_search_phone)

    @router.message(ClientUpdateStates.client_search_phone, F.text)
    async def process_client_phone_search(message: Message, state: FSMContext):
        if not await phone_processing(
            message,
            state,
            final_state=ClientUpdateStates.confirm_search,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_search_to_update_phone_kb())

    # --- Edit search query (before confirming search) ---

    @router.callback_query(
        ClientUpdateStates.confirm_search,
        F.data == "client_search_to_update_edit_full_name",
    )
    async def full_name_edition(callback: CallbackQuery, state: FSMContext):
        await edit_full_name(callback, state, edit_state=ClientUpdateStates.edit_full_name)

    @router.message(ClientUpdateStates.edit_full_name, F.text)
    async def process_full_name_edition(message: Message, state: FSMContext):
        if not await process_edit_full_name(
            message, state,
            final_state=ClientUpdateStates.confirm_search,
            re_pattern=SEARCH_NAME_PATTERN,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_search_to_update_name_kb())

    @router.callback_query(
        ClientUpdateStates.confirm_search,
        F.data == "client_search_to_update_edit_phone",
    )
    async def phone_edition(callback: CallbackQuery, state: FSMContext):
        await edit_phone(callback, state, edit_state=ClientUpdateStates.edit_phone)

    @router.message(ClientUpdateStates.edit_phone, F.text)
    async def process_phone_edition(message: Message, state: FSMContext):
        if not await process_edit_phone(
            message,
            state,
            final_state=ClientUpdateStates.confirm_search,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_search_to_update_phone_kb())

    # --- Show all clients ---

    @router.callback_query(F.data == "get_all_clients_for_update")
    async def get_all_clients_for_update(callback_query: CallbackQuery, state: FSMContext):
        found_clients = await user_repo.get_all_clients()
        await state.set_state(ClientUpdateStates.proceed_update)
        await show_clients_one_be_one(
            callback_query,
            users=found_clients,
            keyboard_factory=choose_to_update_user_kb,
        )

    # --- Confirm search and display results ---

    @router.callback_query(F.data == "approve_client_update_search")
    async def client_update_search_finish(callback_query: CallbackQuery, state: FSMContext):
        data = await state.get_data()

        try:
            found = await cl_mng.search_client(data)
        except (InvalidPhoneError, InvalidFullNameError, UserNotFoundError) as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка поиска клиента: {e}", show_alert=True)
            return

        await state.set_state(ClientUpdateStates.proceed_update)

        await show_clients_one_be_one(
            callback_query,
            users=found,
            keyboard_factory=choose_to_update_user_kb,
        )

    # --- Choose which field to edit ---

    @router.callback_query(
        ClientUpdateStates.proceed_update,
        F.data.startswith("update_name:"),
    )
    async def start_update_name(callback_query: CallbackQuery, state: FSMContext):
        user_id = int(callback_query.data.split(":")[1])
        await state.update_data(user_id=user_id)
        await state.set_state(ClientUpdateStates.new_full_name)
        await callback_query.answer('')
        await callback_query.message.answer(
            "Введите новое ФИО:",
            reply_markup=cancel_kb(),
        )

    @router.callback_query(
        ClientUpdateStates.proceed_update,
        F.data.startswith("update_phone:"),
    )
    async def start_update_phone(callback_query: CallbackQuery, state: FSMContext):
        user_id = int(callback_query.data.split(":")[1])
        await state.update_data(user_id=user_id)
        await state.set_state(ClientUpdateStates.new_phone)
        await callback_query.answer('')
        await callback_query.message.answer(
            "Введите новый телефон:",
            reply_markup=cancel_kb(),
        )

    # --- Cancel during edit: return to client card instead of wiping state ---

    @router.callback_query(
        StateFilter(
            ClientUpdateStates.new_full_name,
            ClientUpdateStates.confirm_new_full_name,
            ClientUpdateStates.new_phone,
            ClientUpdateStates.confirm_new_phone,
        ),
        F.data == "cancel",
    )
    async def cancel_edit(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        user_id = data.get("user_id")

        user = await user_repo.get_client_by_id(user_id)

        await state.set_state(ClientUpdateStates.proceed_update)

        await callback.answer('')
        await callback.message.answer(
            text=build_client_text(
                "Клиент",
                {
                    "user_id": user.ID,
                    "full_name": user.full_name,
                    "phone": user.phone,
                },
            ),
            reply_markup=choose_to_update_user_kb(user.ID),
        )

    # --- Collect and confirm new full name ---

    @router.message(ClientUpdateStates.new_full_name, F.text)
    async def process_new_full_name(message: Message, state: FSMContext):
        if not await full_name_processing(
            message, state,
            next_state=ClientUpdateStates.confirm_new_full_name,
            re_pattern=FULL_NAME_PATTERN,
        ):
            return
        await show_confirmation(message, state, reply_markup=confirm_new_full_name_kb())

    @router.callback_query(
        ClientUpdateStates.confirm_new_full_name,
        F.data == "edit_new_full_name",
    )
    async def re_enter_new_full_name(callback: CallbackQuery, state: FSMContext):
        await edit_full_name(callback, state, edit_state=ClientUpdateStates.new_full_name)

    @router.callback_query(F.data == "approve_update_name")
    async def approve_update_name(callback_query: CallbackQuery, state: FSMContext):
        data = await state.get_data()

        try:
            user = await cl_mng.update_client_name(data["user_id"], data["full_name"])
        except (InvalidFullNameError, UserNotFoundError) as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка обновления клиента: {e}", show_alert=True)
            return

        await show_success(
            callback_query,
            "Имя клиента успешно обновлено!",
            user_id=user.ID,
            full_name=user.full_name,
            phone=user.phone,
        )

        await state.clear()

    # --- Collect and confirm new phone ---

    @router.message(ClientUpdateStates.new_phone, F.text)
    async def process_new_phone(message: Message, state: FSMContext):
        async def validate_update_phone(phone: str):
            data = await state.get_data()
            user_id = data.get("user_id")
            user = await user_repo.get_client_by_id(user_id)
            if user is None:
                raise UserNotFoundError("Клиент не найден.")
            if phone == user.phone:
                raise SamePhoneError("Введён такой же номер телефона, Пожалуйста, введите другой:")
            if await user_repo.phone_exists(phone):
                raise PhoneAlreadyExistsError("Номер уже зарегистрирован. Пожалуйста, введите другой:")

        if not await phone_processing(
            message,
            state,
            validator=validate_update_phone,
            final_state=ClientUpdateStates.confirm_new_phone,
        ):
            return
        await show_confirmation(message, state, reply_markup=confirm_new_phone_kb())

    @router.callback_query(
        ClientUpdateStates.confirm_new_phone,
        F.data == "edit_new_phone",
    )
    async def re_enter_new_phone(callback: CallbackQuery, state: FSMContext):
        await edit_phone(callback, state, edit_state=ClientUpdateStates.new_phone)

    @router.callback_query(F.data == "approve_update_phone")
    async def approve_update_phone(callback_query: CallbackQuery, state: FSMContext):
        data = await state.get_data()

        try:
            user = await cl_mng.update_client_phone(data["user_id"], data["phone"])
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка обновления клиента: {e}", show_alert=True)
            return

        await show_success(
            callback_query,
            "Телефон клиента успешно обновлён!",
            user_id=user.ID,
            full_name=user.full_name,
            phone=user.phone,
        )

        await state.clear()

    return router
