from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from bot.exceptions.exceptions import BotException
from bot.keyboards.client.reminder_cb import ClientReminderPresetCB
from bot.keyboards.client.reminder_kb import reminder_settings_kb
from bot.models.user import User
from bot.services.client.client_management import ClientManagement
from bot.utils.role import Role, RoleFilter


def create_profile_router(client_management_service: ClientManagement = None):

    router = Router()

    router.message.filter(RoleFilter("*"))

    def build_profile_text(user: User) -> str:
        role = "администратор" if user.role == Role.ADMIN else "клиент"

        return (
            "Профиль\n\n"
            f"ФИО: {user.full_name}\n"
            f"ID клиента: {user.ID}\n"
            f"Номер телефона: {user.phone}\n"
            f"Тип пользователя: {role}\n"
            f"Клиника: {user.clinic_name}"
        )

    @router.message(F.text.in_({"/profile", "⚙️ Мой профиль", "👤 Профиль"}), RoleFilter("*"))
    async def profile(message: Message, current_user: User | None = None):

        reply_markup = None
        if client_management_service and current_user.role == Role.CLIENT:
            reply_markup = reminder_settings_kb(current_user.reminder_24h, current_user.reminder_2h)

        await message.answer(build_profile_text(current_user), reply_markup=reply_markup)

    if client_management_service:
        @router.callback_query(ClientReminderPresetCB.filter(), RoleFilter("client"))
        async def update_reminder_preset(
            callback_query: CallbackQuery,
            callback_data: ClientReminderPresetCB,
            current_user: User | None = None,
        ):
            try:
                updated_user = await client_management_service.update_reminder_preferences(
                    current_user.ID, callback_data.preset
                )
            except BotException as e:
                await callback_query.answer(str(e), show_alert=True)
                return

            try:
                await callback_query.message.edit_text(
                    build_profile_text(updated_user),
                    reply_markup=reminder_settings_kb(updated_user.reminder_24h, updated_user.reminder_2h),
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise

            await callback_query.answer("Настройки обновлены")

    return router
