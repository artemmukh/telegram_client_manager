from datetime import datetime

from dataclasses import replace

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommandScopeChat, CallbackQuery, InlineKeyboardButton, Message

from bot.exceptions.exceptions import BotException
from bot.handlers.utils.admin_utils.confirmations import GENDER_LABELS
from bot.keyboards.admin.admin_reminder_cb import AdminReminderPresetCB
from bot.keyboards.admin.admin_reminder_kb import admin_reminder_settings_kb
from bot.keyboards.client.reminder_cb import ClientReminderPresetCB
from bot.keyboards.client.reminder_kb import reminder_settings_kb
from bot.keyboards.common.profile_kb import profile_menu_kb
from bot.keyboards.utils.language_cb import LanguageCB
from bot.keyboards.utils.language_kb import language_settings_kb
from bot.loader import get_bot
from bot.models.user import User
from bot.services.client.client_management import ClientManagement
from bot.utils.commands import admin_commands, client_commands
from bot.utils.role import Role, RoleFilter


PROFILE_TEXTS = {
    "ru": {
        "title": "Профиль",
        "full_name": "ФИ",
        "phone": "Номер телефона",
        "role": "Тип пользователя",
        "clinic_name": "Клиника",
        "birth_date": "Дата рождения",
        "gender": "Пол",
    },
    "uz": {
        "title": "Profil",
        "full_name": "F.I.Sh.",
        "phone": "Telefon raqami",
        "role": "Foydalanuvchi turi",
        "clinic_name": "Klinika",
        "birth_date": "Tug'ilgan sana",
        "gender": "Jinsi",
    },
}

ROLE_LABELS = {
    "ru": {"admin": "администратор", "client": "клиент"},
    "uz": {"admin": "administrator", "client": "mijoz"},
}

SETTINGS_UPDATED_TEXT = {
    "ru": "Настройки обновлены",
    "uz": "Sozlamalar yangilandi",
}

BACK_BUTTON_TEXT = {
    "ru": "⬅️ Назад",
    "uz": "⬅️ Orqaga",
}


def build_profile_text(user: User, lang: str = "ru") -> str:
    texts = PROFILE_TEXTS.get(lang, PROFILE_TEXTS["ru"])
    role_labels = ROLE_LABELS.get(lang, ROLE_LABELS["ru"])
    role = role_labels["admin"] if user.role == Role.ADMIN else role_labels["client"]

    lines = [
        f"{texts['title']}\n",
        f"{texts['full_name']}: {user.full_name}",
        f"{texts['phone']}: {user.phone}",
        f"{texts['role']}: {role}",
        f"{texts['clinic_name']}: {user.clinic_name}",
    ]

    if user.birth_date:
        display_birth_date = datetime.strptime(user.birth_date, "%Y-%m-%d").strftime("%d.%m.%Y")
        lines.append(f"{texts['birth_date']}: {display_birth_date}")
    if user.gender:
        gender_labels = GENDER_LABELS.get(lang, GENDER_LABELS["ru"])
        lines.append(f"{texts['gender']}: {gender_labels.get(user.gender, user.gender)}")

    return "\n".join(lines)


def create_profile_router(client_management_service: ClientManagement = None):

    router = Router()

    router.message.filter(RoleFilter("*"))

    def _with_back_button(reply_markup, lang: str = "ru"):
        reply_markup.inline_keyboard.append(
            [InlineKeyboardButton(text=BACK_BUTTON_TEXT.get(lang, BACK_BUTTON_TEXT["ru"]), callback_data="profile_back")]
        )
        return reply_markup

    @router.message(
        F.text.in_({"/profile", "⚙️ Мой профиль", "👤 Профиль", "⚙️ Mening profilim", "👤 Profil"}),
        RoleFilter("*"),
    )
    async def profile(message: Message, current_user: User | None = None):

        reply_markup = profile_menu_kb(lang=current_user.language) if client_management_service else None

        await message.answer(build_profile_text(current_user, current_user.language), reply_markup=reply_markup)

    if client_management_service:
        @router.callback_query(F.data == "profile_reminder_settings", RoleFilter("*"))
        async def open_reminder_settings(callback_query: CallbackQuery, current_user: User | None = None):
            if current_user.role == Role.ADMIN:
                reply_markup = admin_reminder_settings_kb(
                    current_user.reminder_24h, current_user.reminder_2h, lang=current_user.language,
                )
            else:
                reply_markup = reminder_settings_kb(
                    current_user.reminder_24h, current_user.reminder_2h, lang=current_user.language,
                )

            await callback_query.message.edit_text(
                build_profile_text(current_user, current_user.language),
                reply_markup=_with_back_button(reply_markup, current_user.language),
            )
            await callback_query.answer()

        @router.callback_query(F.data == "profile_language_settings", RoleFilter("*"))
        async def open_language_settings(callback_query: CallbackQuery, current_user: User | None = None):
            await callback_query.message.edit_text(
                build_profile_text(current_user, current_user.language),
                reply_markup=_with_back_button(language_settings_kb(current_user.language), current_user.language),
            )
            await callback_query.answer()

        @router.callback_query(LanguageCB.filter(), RoleFilter("*"))
        async def update_language_preset(
            callback_query: CallbackQuery,
            callback_data: LanguageCB,
            current_user: User | None = None,
        ):
            try:
                updated_user = await client_management_service.update_language(
                    current_user.ID, callback_data.value
                )
            except BotException as e:
                await callback_query.answer(e.localized(current_user.language), show_alert=True)
                return

            updated_user = replace(updated_user, role=current_user.role)

            try:
                await callback_query.message.edit_text(
                    build_profile_text(updated_user, updated_user.language),
                    reply_markup=_with_back_button(language_settings_kb(updated_user.language), updated_user.language),
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise

            if updated_user.telegram_user_id:
                commands = (
                    admin_commands(updated_user.language)
                    if updated_user.role == Role.ADMIN
                    else client_commands(updated_user.language)
                )
                bot = get_bot()
                await bot.set_my_commands(
                    commands, scope=BotCommandScopeChat(chat_id=updated_user.telegram_user_id)
                )

            await callback_query.answer(SETTINGS_UPDATED_TEXT.get(updated_user.language, SETTINGS_UPDATED_TEXT["ru"]))

        @router.callback_query(F.data == "profile_back", RoleFilter("*"))
        async def back_to_profile(callback_query: CallbackQuery, state: FSMContext, current_user: User | None = None):
            await state.clear()
            reply_markup = profile_menu_kb(lang=current_user.language)

            try:
                await callback_query.message.edit_text(
                    build_profile_text(current_user, current_user.language), reply_markup=reply_markup
                )
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
                await callback_query.answer(e.localized(current_user.language), show_alert=True)
                return

            try:
                await callback_query.message.edit_text(
                    build_profile_text(updated_user, updated_user.language),
                    reply_markup=_with_back_button(
                        reminder_settings_kb(
                            updated_user.reminder_24h, updated_user.reminder_2h, lang=updated_user.language,
                        ),
                        updated_user.language,
                    ),
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise

            await callback_query.answer(SETTINGS_UPDATED_TEXT.get(updated_user.language, SETTINGS_UPDATED_TEXT["ru"]))

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
                await callback_query.answer(e.localized(current_user.language), show_alert=True)
                return

            try:
                await callback_query.message.edit_text(
                    build_profile_text(updated_user, updated_user.language),
                    reply_markup=_with_back_button(
                        admin_reminder_settings_kb(
                            updated_user.reminder_24h, updated_user.reminder_2h, lang=updated_user.language,
                        ),
                        updated_user.language,
                    ),
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise

            await callback_query.answer(SETTINGS_UPDATED_TEXT.get(updated_user.language, SETTINGS_UPDATED_TEXT["ru"]))

    return router
