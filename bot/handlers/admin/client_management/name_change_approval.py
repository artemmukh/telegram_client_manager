from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import UserNotFoundError
from bot.keyboards.admin.name_change_cb import NameChangeApprovalCB
from bot.models.user import User
from bot.services.client.client_management import ClientManagement
from bot.utils.role import RoleFilter

_ALREADY_RESOLVED = {
    "ru": "Запрос уже обработан другим администратором.",
    "uz": "So'rov boshqa administrator tomonidan allaqachon ko'rib chiqilgan.",
}

_NAME_UPDATED = {
    "ru": "✅ ФИ обновлено: {name}",
    "uz": "✅ F.I.Sh. yangilandi: {name}",
}

_APPROVED_CLIENT_NOTICE = {
    "ru": "✅ Ваш запрос на смену ФИ одобрен.\nНовое ФИ: {name}",
    "uz": "✅ F.I.Sh.ni o'zgartirish so'rovingiz tasdiqlandi.\nYangi F.I.Sh.: {name}",
}

_REQUEST_REJECTED = {
    "ru": "❌ Запрос на смену ФИ отклонён.",
    "uz": "❌ F.I.Sh.ni o'zgartirish so'rovi rad etildi.",
}

_REJECTED_CLIENT_NOTICE = {
    "ru": "❌ Ваш запрос на смену ФИ отклонён администратором.",
    "uz": "❌ F.I.Sh.ni o'zgartirish so'rovingiz administrator tomonidan rad etildi.",
}


def create_admin_name_change_router(user_repo, staff_repo, clinic_repo, client_clinic_repo=None) -> Router:
    router = Router()

    cl_mng = ClientManagement(
        user_repository=user_repo,
        staff_repository=staff_repo,
        clinic_repository=clinic_repo,
        client_clinic_repository=client_clinic_repo,
    )

    router.callback_query.filter(RoleFilter("admin"))

    async def mark_already_resolved(callback_query: CallbackQuery, lang: str) -> None:
        await callback_query.answer(_ALREADY_RESOLVED.get(lang, _ALREADY_RESOLVED["ru"]), show_alert=True)
        try:
            await callback_query.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise

    @router.callback_query(NameChangeApprovalCB.filter(F.action == "approve"))
    async def approve_name_change(callback_query: CallbackQuery, callback_data: NameChangeApprovalCB, current_user: User):
        admin_lang = current_user.language
        try:
            clinic = await cl_mng.get_admin_clinic(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(e.localized(admin_lang), show_alert=True)
            return

        try:
            user = await cl_mng.approve_name_change(callback_data.user_id, clinic.clinic_id)
        except UserNotFoundError as e:
            await callback_query.answer(e.localized(admin_lang), show_alert=True)
            return

        if user is None:
            await mark_already_resolved(callback_query, admin_lang)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(_NAME_UPDATED.get(admin_lang, _NAME_UPDATED["ru"]).format(name=user.full_name))

        if user.telegram_user_id is not None:
            await callback_query.bot.send_message(
                chat_id=user.telegram_user_id,
                text=_APPROVED_CLIENT_NOTICE.get(user.language, _APPROVED_CLIENT_NOTICE["ru"]).format(name=user.full_name),
            )

    @router.callback_query(NameChangeApprovalCB.filter(F.action == "reject"))
    async def reject_name_change(callback_query: CallbackQuery, callback_data: NameChangeApprovalCB, current_user: User):
        admin_lang = current_user.language
        try:
            clinic = await cl_mng.get_admin_clinic(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(e.localized(admin_lang), show_alert=True)
            return

        try:
            user = await cl_mng.reject_name_change(callback_data.user_id, clinic.clinic_id)
        except UserNotFoundError as e:
            await callback_query.answer(e.localized(admin_lang), show_alert=True)
            return

        if user is None:
            await mark_already_resolved(callback_query, admin_lang)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(_REQUEST_REJECTED.get(admin_lang, _REQUEST_REJECTED["ru"]))

        if user.telegram_user_id is not None:
            await callback_query.bot.send_message(
                chat_id=user.telegram_user_id,
                text=_REJECTED_CLIENT_NOTICE.get(user.language, _REJECTED_CLIENT_NOTICE["ru"]),
            )

    return router
