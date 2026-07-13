from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from bot.keyboards.admin.name_change_cb import NameChangeApprovalCB
from bot.services.client.client_management import ClientManagement
from bot.utils.role import RoleFilter


def create_admin_name_change_router(user_repo, staff_repo, clinic_repo) -> Router:
    router = Router()

    cl_mng = ClientManagement(user_repo, staff_repo, clinic_repo)

    router.callback_query.filter(RoleFilter("admin"))

    async def mark_already_resolved(callback_query: CallbackQuery) -> None:
        await callback_query.answer("Запрос уже обработан другим администратором.", show_alert=True)
        try:
            await callback_query.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise

    @router.callback_query(NameChangeApprovalCB.filter(F.action == "approve"))
    async def approve_name_change(callback_query: CallbackQuery, callback_data: NameChangeApprovalCB):
        user = await cl_mng.approve_name_change(callback_data.user_id)

        if user is None:
            await mark_already_resolved(callback_query)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(f"✅ ФИ обновлено: {user.full_name}")

        if user.telegram_user_id is not None:
            await callback_query.bot.send_message(
                chat_id=user.telegram_user_id,
                text=f"✅ Ваш запрос на смену ФИ одобрен.\nНовое ФИ: {user.full_name}",
            )

    @router.callback_query(NameChangeApprovalCB.filter(F.action == "reject"))
    async def reject_name_change(callback_query: CallbackQuery, callback_data: NameChangeApprovalCB):
        user = await cl_mng.reject_name_change(callback_data.user_id)

        if user is None:
            await mark_already_resolved(callback_query)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text("❌ Запрос на смену ФИ отклонён.")

        if user.telegram_user_id is not None:
            await callback_query.bot.send_message(
                chat_id=user.telegram_user_id,
                text="❌ Ваш запрос на смену ФИ отклонён администратором.",
            )

    return router
