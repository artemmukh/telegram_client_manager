from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.exceptions import BotException
from bot.handlers.utils.admin_utils.client_browser_helpers import render_client_card
from bot.keyboards.admin.record_management_kb.record_main_menu_kb import record_keyboard
from bot.models.user import User
from bot.services.client.client_management import ClientManagement
from bot.utils.role import RoleFilter

_CHOOSE_RECORD_ACTION = {
    "ru": "Выберите действие над записью:",
    "uz": "Yozuv uchun amalni tanlang:",
}


def create_admin_record_router(user_repo, staff_repo, clinic_repo, client_clinic_repo=None):

    router = Router()

    cl_mng = ClientManagement(
        user_repository=user_repo,
        staff_repository=staff_repo,
        clinic_repository=clinic_repo,
        client_clinic_repository=client_clinic_repo,
    )

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    @router.message(F.text.in_({
        "/record_managing", "📒 Управление записями", "📅 Календарь",
        "📒 Yozuvlarni boshqarish", "📅 Kalendar",
    }))
    async def record_managing(message: Message, current_user: User):
        lang = current_user.language
        await message.answer(
            text=_CHOOSE_RECORD_ACTION.get(lang, _CHOOSE_RECORD_ACTION["ru"]), reply_markup=record_keyboard(lang=lang),
        )

    @router.callback_query(F.data == "back_to_main_records")
    async def back_to_main(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        data = await state.get_data()
        if data.get("client_preselected"):
            origin_client_id = data.get("origin_client_id")
            origin_mode = data.get("origin_mode")
            origin_page = data.get("origin_page")
            origin_search_data = data.get("origin_search_data")
            await state.clear()
            if origin_search_data is not None:
                await state.update_data(search_data=origin_search_data)
            try:
                clinic = await cl_mng.get_admin_clinic(callback_query.from_user.id)
            except BotException as e:
                await callback_query.answer(e.localized(lang), show_alert=True)
                return
            found = await render_client_card(
                cl_mng, callback_query, state, origin_client_id, origin_mode, origin_page, clinic.clinic_id, lang,
            )
            if not found:
                await callback_query.message.edit_text(
                    _CHOOSE_RECORD_ACTION.get(lang, _CHOOSE_RECORD_ACTION["ru"]),
                    reply_markup=record_keyboard(lang=lang)
                )
            return

        await state.clear()
        await callback_query.answer('')
        await callback_query.message.edit_text(
            _CHOOSE_RECORD_ACTION.get(lang, _CHOOSE_RECORD_ACTION["ru"]),
            reply_markup=record_keyboard(lang=lang)
        )

    return router