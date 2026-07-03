from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import InvalidPhoneError, InvalidFullNameError, UserNotFoundError, RoleError
from bot.handlers.utils.admin_utils.confirmations import show_success, show_confirmation, build_users_list_text, \
    show_users, show_user
from bot.handlers.utils.admin_utils.input_helpers import ask_full_name, edit_full_name, phone_processing, \
    full_name_processing, \
    process_edit_full_name, edit_phone, process_edit_phone, ask_phone
from bot.keyboards.admin.client_management_kb.client_deletion_kb import client_deletion_kb, \
    client_deletion_proceeding_kb, client_search_to_delete_phone_kb, \
    client_search_to_delete_name_kb, choose_to_delete_user_kb
from bot.keyboards.admin.client_management_kb.client_search_kb import client_search_phone_kb, client_search_name_kb
from bot.services.client.client_management import ClientManagement
from bot.states.admin.client_management.client_deletion_states import ClientDeletionStates
from bot.utils.role import RoleFilter
from bot.validators.validators import SEARCH_NAME_PATTERN


def create_admin_client_deletion_router(user_repo):
    router = Router()

    cl_mng = ClientManagement(user_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    @router.callback_query(F.data == "delete_client")
    async def client_delete(callback_query: CallbackQuery):
        await callback_query.answer('')
        await callback_query.message.edit_text(text='Выберите метод поиска для удаления:',
                                               reply_markup=client_deletion_kb())

    @router.callback_query(F.data == "client_full_name_deletion")
    async def client_full_name_search(callback_query: CallbackQuery, state: FSMContext):
        await ask_full_name(callback_query, state, next_state=ClientDeletionStates.client_search_name)

    @router.message(ClientDeletionStates.client_search_name, F.text)
    async def process_client_full_name_search(message: Message, state: FSMContext):
        if not await full_name_processing(message, state, next_state=ClientDeletionStates.confirm_deletion,
                                          re_pattern=SEARCH_NAME_PATTERN):
            return
        await show_confirmation(message, state, reply_markup=client_search_to_delete_name_kb())

    @router.callback_query(F.data == "client_phone_deletion")
    async def client_phone_search(callback_query: CallbackQuery, state: FSMContext):
        await ask_phone(callback_query, state, ClientDeletionStates.client_search_phone)

    @router.message(ClientDeletionStates.client_search_phone, F.text)
    async def process_client_phone_search(message: Message, state: FSMContext):
        if not await phone_processing(
                message,
                state,
                final_state=ClientDeletionStates.confirm_deletion,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_search_to_delete_phone_kb())

    @router.callback_query(ClientDeletionStates.confirm_deletion,
                           F.data == "client_search_to_delete_edit_full_name")
    async def full_name_edition(callback: CallbackQuery, state: FSMContext):
        await edit_full_name(callback, state, edit_state=ClientDeletionStates.edit_full_name)

    @router.message(ClientDeletionStates.edit_full_name, F.text)
    async def process_full_name_edition(message: Message, state: FSMContext):
        if not await process_edit_full_name(
                message, state,
                final_state=ClientDeletionStates.confirm_deletion, re_pattern=SEARCH_NAME_PATTERN
        ):
            return
        await show_confirmation(message, state, reply_markup=client_search_to_delete_name_kb())

    @router.callback_query(
        ClientDeletionStates.confirm_deletion,
        F.data == "client_search_to_delete_edit_phone"
    )
    async def phone_edition(callback: CallbackQuery, state: FSMContext):
        await edit_phone(callback, state, edit_state=ClientDeletionStates.edit_phone)

    @router.message(ClientDeletionStates.edit_phone, F.text)
    async def process_phone_edition(message: Message, state: FSMContext):
        if not await process_edit_phone(
                message,
                state,
                final_state=ClientDeletionStates.confirm_deletion,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_search_to_delete_phone_kb())

    @router.callback_query(F.data == "approve_client_delete")
    async def client_deletion_confirm(callback_query: CallbackQuery, state: FSMContext):

        data = await state.get_data()

        try:
            found = await cl_mng.search_client(data)

        except (InvalidPhoneError, InvalidFullNameError, UserNotFoundError) as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка поиска клиента: {e}", show_alert=True)
            return

        if len(found) == 1:
            user = found[0]

            await state.update_data(
                user_id=user.ID,
                full_name=user.full_name,
                phone=user.phone,
            )

            await state.set_state(ClientDeletionStates.proceed_deletion)

            await show_success(
                callback_query,
                "Клиент на удаление:",
                user_id=user.ID,
                full_name=user.full_name,
                phone=user.phone,
            )

            await callback_query.message.edit_reply_markup(
                reply_markup=client_deletion_proceeding_kb()
            )
            return

        # Несколько клиентов
        await state.set_state(ClientDeletionStates.proceed_deletion)

        await show_user(
            callback_query,
            users=found,
            keyboard_factory=choose_to_delete_user_kb,
        )

    @router.callback_query(
        ClientDeletionStates.proceed_deletion,
        F.data.startswith("delete:")
    )
    async def choose_client(callback_query: CallbackQuery, state: FSMContext):

        await callback_query.answer("Внимание!\n"
                                    "Вы подтверждаете удаление клиента!", shown_alert=True)

        user_id = int(callback_query.data.split(":")[1])

        user = await user_repo.get_user_by_id(user_id)

        await state.update_data(
            user_id=user.ID,
            full_name=user.full_name,
            phone=user.phone,
        )

        await show_success(
            callback_query,
            "Клиент на удаление:",
            user_id=user.ID,
            full_name=user.full_name,
            phone=user.phone,
        )

        await callback_query.message.edit_reply_markup(
            reply_markup=client_deletion_proceeding_kb()
        )




    @router.callback_query(F.data == "approve_deletion")
    async def client_deletion_finish(callback_query: CallbackQuery, state: FSMContext):
        try:
            data = await state.get_data()
            print(data)
            try:
                await cl_mng.delete_client(data["user_id"])
            except BotException as e:
                await callback_query.answer(str(e))


            await callback_query.message.edit_text(f"Клиент {data['full_name']} успешно удален из БД!")

            await state.clear()
        except RoleError as e:
            await callback_query.answer(str(e), show_alert=True)
            return



    return router
