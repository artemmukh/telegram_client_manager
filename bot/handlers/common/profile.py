import asyncio
import logging
from dataclasses import replace
from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BotCommandScopeChat,
    CallbackQuery,
    InlineKeyboardButton,
    Message,
)

from bot.exceptions.exceptions import BotException
from bot.handlers.utils.admin_utils.confirmations import GENDER_LABELS
from bot.keyboards.admin.admin_reminder_cb import AdminReminderPresetCB
from bot.keyboards.admin.admin_reminder_kb import admin_reminder_settings_kb
from bot.keyboards.admin.broadcast_kb import (
    broadcast_confirmation_kb,
    broadcast_preview_kb,
)
from bot.keyboards.client.reminder_cb import ClientReminderPresetCB
from bot.keyboards.client.reminder_kb import reminder_settings_kb
from bot.keyboards.common.profile_kb import profile_menu_kb
from bot.keyboards.utils.language_cb import LanguageCB
from bot.keyboards.utils.language_kb import language_settings_kb
from bot.loader import get_bot
from bot.models.user import User
from bot.services.client.client_management import ClientManagement
from bot.services.client.client_notifications import (
    APPROVED_BROADCAST_TEXT,
    ClientNotificationService,
)
from bot.services.utils.escape_html import escape_html
from bot.states.admin.broadcast_states import BroadcastStates
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

DEFAULT_BROADCAST_TEXT = APPROVED_BROADCAST_TEXT

BROADCAST_EDIT_PROMPT = "Отправьте новый текст рассылки одним сообщением."
BROADCAST_CONFIRMATION_TEXT = "Отправить это сообщение всем клиентам?"
BROADCAST_STARTED_TEXT = "Рассылка запущена. После завершения здесь появится итог."
BROADCAST_RUNNING_TEXT = "Рассылка уже выполняется."
BROADCAST_FAILED_TEXT = "Рассылка завершилась с ошибкой. Подробности записаны в журнал."
BROADCAST_SUMMARY_TEXT = "Рассылка завершена. Отправлено: {sent}; ошибок: {failed}; пропущено: {skipped}."

logger = logging.getLogger(__name__)


def _broadcast_preview_text(text: str) -> str:
    return text if text == DEFAULT_BROADCAST_TEXT else escape_html(text)


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


def create_profile_router(
    client_management_service: ClientManagement = None,
    broadcast_service: ClientNotificationService | None = None,
):

    router = Router()

    router.message.filter(RoleFilter("*"))

    def _with_back_button(reply_markup, lang: str = "ru"):
        reply_markup.inline_keyboard.append(
            [InlineKeyboardButton(text=BACK_BUTTON_TEXT.get(lang, BACK_BUTTON_TEXT["ru"]), callback_data="profile_back")]
        )
        return reply_markup

    async def _safe_edit_broadcast_status(message: Message, text: str) -> None:
        try:
            await message.edit_text(text)
        except Exception:
            logger.exception("Failed to update one-time broadcast status")

    async def _report_broadcast_result(task: asyncio.Task, message: Message) -> None:
        try:
            summary = await task
            summary_text = BROADCAST_SUMMARY_TEXT.format(
                sent=summary.sent,
                failed=summary.failed,
                skipped=summary.skipped,
            )
        except Exception:
            logger.exception("One-time client broadcast failed")
            await _safe_edit_broadcast_status(message, BROADCAST_FAILED_TEXT)
            return

        await _safe_edit_broadcast_status(message, summary_text)

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
                    current_user.reminder_24h,
                    current_user.reminder_2h,
                    lang=current_user.language,
                    show_broadcast=broadcast_service is not None,
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

        if broadcast_service:
            @router.callback_query(F.data == "profile_broadcast_settings", RoleFilter("admin"))
            async def open_broadcast_preview(
                callback_query: CallbackQuery,
                state: FSMContext,
                current_user: User | None = None,
            ):
                data = await state.get_data()
                text = data.get("broadcast_text", DEFAULT_BROADCAST_TEXT)
                await state.update_data(broadcast_text=text)
                await callback_query.message.edit_text(
                    _broadcast_preview_text(text),
                    reply_markup=broadcast_preview_kb(),
                )
                await callback_query.answer()

            @router.callback_query(F.data == "broadcast_edit_text", RoleFilter("admin"))
            async def edit_broadcast_text(
                callback_query: CallbackQuery,
                state: FSMContext,
                current_user: User | None = None,
            ):
                await state.set_state(BroadcastStates.edit_text)
                await callback_query.message.edit_text(BROADCAST_EDIT_PROMPT)
                await callback_query.answer()

            @router.message(BroadcastStates.edit_text, F.text, RoleFilter("admin"))
            async def receive_broadcast_text(
                message: Message,
                state: FSMContext,
                current_user: User | None = None,
            ):
                await state.update_data(broadcast_text=message.text)
                await state.set_state(None)
                await message.answer(_broadcast_preview_text(message.text), reply_markup=broadcast_preview_kb())

            @router.callback_query(F.data == "broadcast_send", RoleFilter("admin"))
            async def request_broadcast_send(
                callback_query: CallbackQuery,
                state: FSMContext,
                current_user: User | None = None,
            ):
                data = await state.get_data()
                await state.update_data(broadcast_text=data.get("broadcast_text", DEFAULT_BROADCAST_TEXT))
                await state.set_state(BroadcastStates.confirm_send)
                await callback_query.message.edit_text(
                    BROADCAST_CONFIRMATION_TEXT,
                    reply_markup=broadcast_confirmation_kb(),
                )
                await callback_query.answer()

            @router.callback_query(
                BroadcastStates.confirm_send,
                F.data == "broadcast_cancel",
                RoleFilter("admin"),
            )
            async def cancel_broadcast_send(
                callback_query: CallbackQuery,
                state: FSMContext,
                current_user: User | None = None,
            ):
                data = await state.get_data()
                await state.set_state(None)
                await callback_query.message.edit_text(
                    _broadcast_preview_text(data.get("broadcast_text", DEFAULT_BROADCAST_TEXT)),
                    reply_markup=broadcast_preview_kb(),
                )
                await callback_query.answer()

            @router.callback_query(
                BroadcastStates.confirm_send,
                F.data == "broadcast_confirm",
                RoleFilter("admin"),
            )
            async def confirm_broadcast_send(
                callback_query: CallbackQuery,
                state: FSMContext,
                current_user: User | None = None,
            ):
                data = await state.get_data()
                text = data.get("broadcast_text", DEFAULT_BROADCAST_TEXT)
                await _safe_edit_broadcast_status(callback_query.message, BROADCAST_STARTED_TEXT)

                try:
                    task = await broadcast_service.start_broadcast(text)
                except Exception:
                    logger.exception("Failed to start one-time client broadcast")
                    await _safe_edit_broadcast_status(callback_query.message, BROADCAST_FAILED_TEXT)
                    await callback_query.answer(BROADCAST_FAILED_TEXT, show_alert=True)
                    return

                if task is None:
                    await _safe_edit_broadcast_status(callback_query.message, BROADCAST_RUNNING_TEXT)
                    await callback_query.answer(BROADCAST_RUNNING_TEXT, show_alert=True)
                    return

                await state.clear()
                asyncio.create_task(_report_broadcast_result(task, callback_query.message))
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
                            updated_user.reminder_24h,
                            updated_user.reminder_2h,
                            lang=updated_user.language,
                            show_broadcast=broadcast_service is not None,
                        ),
                        updated_user.language,
                    ),
                )
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e):
                    raise

            await callback_query.answer(SETTINGS_UPDATED_TEXT.get(updated_user.language, SETTINGS_UPDATED_TEXT["ru"]))

    return router
