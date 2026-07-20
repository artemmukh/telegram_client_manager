from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.handlers.utils.admin_utils.client_browser_helpers import render_client_card
from bot.keyboards.admin.record_management_kb.record_main_menu_kb import record_keyboard
from bot.services.client.client_management import ClientManagement
from bot.utils.role import RoleFilter


def create_admin_record_router(user_repo, staff_repo, clinic_repo):

    router = Router()

    cl_mng = ClientManagement(user_repo, staff_repo, clinic_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    @router.message(F.text.in_({"/record_managing", "📒 Управление записями", "📅 Календарь"}))
    async def record_managing(message: Message):
        await message.answer(text="Выберите действие над записью:", reply_markup=record_keyboard())

    @router.callback_query(F.data == "back_to_main_records")
    async def back_to_main(callback_query: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        if data.get("client_preselected"):
            origin_client_id = data.get("origin_client_id")
            origin_mode = data.get("origin_mode")
            origin_page = data.get("origin_page")
            origin_search_data = data.get("origin_search_data")
            await state.clear()
            if origin_search_data is not None:
                await state.update_data(search_data=origin_search_data)
            found = await render_client_card(cl_mng, callback_query, state, origin_client_id, origin_mode, origin_page)
            if not found:
                await callback_query.message.edit_text(
                    "Выберите действие над записью:",
                    reply_markup=record_keyboard()
                )
            return

        await state.clear()
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Выберите действие над записью:",
            reply_markup=record_keyboard()
        )

    return router