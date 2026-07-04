from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import InvalidPhoneError, InvalidFullNameError, UserNotFoundError
from bot.handlers.utils.admin_utils.confirmations import show_success, show_confirmation, show_all_clients
from bot.handlers.utils.admin_utils.input_helpers import ask_full_name, edit_full_name, phone_processing, \
    full_name_processing, \
    process_edit_full_name, edit_phone, process_edit_phone, ask_phone
from bot.keyboards.admin.client_management_kb.client_search_kb import client_search_kb, \
    client_search_phone_kb, client_search_name_kb
from bot.utils.role import RoleFilter
from bot.validators.validators import SEARCH_NAME_PATTERN
from bot.services.client.client_management import ClientManagement
from bot.states.admin.client_management.client_search_states import ClientSearchStates


def create_admin_client_search_router(user_repo):
    router = Router()

    cl_mng = ClientManagement(user_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    @router.callback_query(F.data == "search_client")
    async def client_search(callback_query: CallbackQuery):
        await callback_query.answer('')
        await callback_query.message.edit_text(text='Выберите метод поиска:', reply_markup=client_search_kb())

    @router.callback_query(F.data == "client_full_name_search")
    async def client_full_name_search(callback_query: CallbackQuery, state: FSMContext):
        await ask_full_name(callback_query, state, next_state=ClientSearchStates.client_search_name)

    @router.message(ClientSearchStates.client_search_name, F.text)
    async def process_client_full_name_search(message: Message, state: FSMContext):
        if not await full_name_processing(message, state, next_state=ClientSearchStates.confirm_search, re_pattern=SEARCH_NAME_PATTERN):
            return
        await show_confirmation(message, state, reply_markup=client_search_name_kb())

    @router.callback_query(F.data == "client_phone_search")
    async def client_phone_search(callback_query: CallbackQuery, state: FSMContext):
        await ask_phone(callback_query, state, ClientSearchStates.client_search_phone)

    @router.message(ClientSearchStates.client_search_phone, F.text)
    async def process_client_phone_search(message: Message, state: FSMContext):
        if not await phone_processing(
            message,
            state,
            final_state=ClientSearchStates.confirm_search,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_search_phone_kb())

    @router.callback_query(ClientSearchStates.confirm_search, F.data == "client_search_edit_full_name")
    async def full_name_edition(callback: CallbackQuery, state: FSMContext):
        await edit_full_name(callback, state, edit_state=ClientSearchStates.edit_full_name)

    @router.message(ClientSearchStates.edit_full_name, F.text)
    async def process_full_name_edition(message: Message, state: FSMContext):
        if not await process_edit_full_name(
                message, state,
                final_state=ClientSearchStates.confirm_search, re_pattern=SEARCH_NAME_PATTERN
        ):
            return
        await show_confirmation(message, state, reply_markup=client_search_name_kb())

    @router.callback_query(
        ClientSearchStates.confirm_search,
        F.data == "client_search_edit_phone"
    )
    async def phone_edition(callback: CallbackQuery, state: FSMContext):
        await edit_phone(callback, state, edit_state=ClientSearchStates.edit_phone)

    @router.message(ClientSearchStates.edit_phone, F.text)
    async def process_phone_edition(message: Message, state: FSMContext):
        if not await process_edit_phone(
            message,
            state,
            final_state=ClientSearchStates.confirm_search,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_search_phone_kb())

    @router.callback_query(F.data == "get_all_clients")
    async def get_all_clients(callback_query: CallbackQuery, state: FSMContext):
        found_clients = await user_repo.get_all_clients()
        await show_all_clients(callback_query, f"Список всех клиентов (всего: {len(found_clients)}): "
                               , users=found_clients)

    @router.callback_query(F.data == "approve_client_search")
    async def client_search_finish(callback_query: CallbackQuery, state: FSMContext):

        data = await state.get_data()

        try:
            found = await cl_mng.search_client(data)
        except (InvalidPhoneError, InvalidFullNameError, UserNotFoundError) as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка поиска клиента: {e}", show_alert=True)
            return



        await show_all_clients(
            callback_query,
            f"Клиентов найдено: {len(found)}",
            users=found,
        )


        await state.clear()

    return router
