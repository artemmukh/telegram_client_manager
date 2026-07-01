from aiogram import Router, F
from aiogram.fsm.context import FSMContext

from bot.keyboards.admin.client_management_kb.client_deletion_kb import client_deletion_kb
from bot.keyboards.utils.utils_kb import cancel_kb
from bot.services.client.client_management import ClientManagement
from bot.states.admin.client_management.client_delition_states import ClientDeletionStates


def create_admin_client_delete_router(user_repo):


    router = Router()

    cl_mng = ClientManagement(user_repo)


    @router.callback_query(F.data == "delete_client")
    async def delete_client(callback_query: F.CallbackQuery, state: FSMContext):
        await state.set_state(ClientDeletionStates.client_search_variant)
        await callback_query.answer('')
        await callback_query.message.edit_text(text="Выберите метод поиска для удаления:", reply_markup=client_deletion_kb())


    @router.message(ClientDeletionStates.client_search_variant, F.text)
    async def delete_client_by_phone(message: F.Message, state: FSMContext):
        pass






    return router