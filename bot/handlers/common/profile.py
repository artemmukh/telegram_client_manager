from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

from bot.exceptions.exceptions import BotException
from bot.keyboards.admin.admin_reminder_cb import AdminReminderPresetCB
from bot.keyboards.admin.admin_reminder_kb import admin_reminder_settings_kb
from bot.keyboards.client.reminder_cb import ClientReminderPresetCB
from bot.keyboards.client.reminder_kb import reminder_settings_kb
from bot.keyboards.common.profile_kb import profile_menu_kb
from bot.models.user import User
from bot.services.client.client_management import ClientManagement
from bot.utils.role import Role, RoleFilter


def create_profile_router(client_management_service: ClientManagement = None):

    router = Router()

    router.message.filter(RoleFilter("*"))

    def _with_back_button(reply_markup):
        reply_markup.inline_keyboard.append(
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile_back")]
        )
        return reply_markup

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

        reply_markup = profile_menu_kb() if client_management_service else None

        await message.answer(build_profile_text(current_user), reply_markup=reply_markup)

    if client_management_service:
        @router.callback_query(F.data == "profile_reminder_settings", RoleFilter("*"))
        async def open_reminder_settings(callback_query: CallbackQuery, current_user: User | None = None):
            if current_user.role == Role.ADMIN:
                reply_markup = admin_reminder_settings_kb(current_user.reminder_24h, current_user.reminder_2h)
            else:
                reply_markup = reminder_settings_kb(current_user.reminder_24h, current_user.reminder_2h)

            await callback_query.message.edit_text(
                build_profile_text(current_user), reply_markup=_with_back_button(reply_markup)
            )
            await callback_query.answer()

        @router.callback_query(F.data == "profile_back", RoleFilter("*"))
        async def back_to_profile(callback_query: CallbackQuery, state: FSMContext, current_user: User | None = None):
            await state.clear()
            reply_markup = profile_menu_kb()

            try:
                await callback_query.message.edit_text(build_profile_text(current_user), reply_markup=reply_markup)
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise

            await callback_query.answer()

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
                    reply_markup=_with_back_button(
                        reminder_settings_kb(updated_user.reminder_24h, updated_user.reminder_2h)
                    ),
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise

            await callback_query.answer("Настройки обновлены")

        @router.callback_query(AdminReminderPresetCB.filter(), RoleFilter("admin"))
        async def update_admin_reminder_preset(
            callback_query: CallbackQuery,
            callback_data: AdminReminderPresetCB,
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
                    reply_markup=_with_back_button(
                        admin_reminder_settings_kb(updated_user.reminder_24h, updated_user.reminder_2h)
                    ),
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise

            await callback_query.answer("Настройки обновлены")

    return router
