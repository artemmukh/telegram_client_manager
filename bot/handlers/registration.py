from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, BotCommandScopeChat

import bot.messages.common as msg
from bot.exceptions.user_exceptions import ContactOwnershipMismatchError, PhoneAlreadyExistsError, \
    UserAlreadyExistsError
from bot.handlers.utils.admin_utils.confirmations import show_confirmation
from bot.handlers.utils.admin_utils.input_helpers import (
    birth_date_processing, edit_full_name, full_name_processing

)
from bot.keyboards.utils.gender_cb import GenderCB
from bot.keyboards.utils.gender_kb import gender_kb
from bot.keyboards.utils.language_cb import LanguageCB
from bot.keyboards.utils.language_kb import language_kb
from bot.keyboards.utils.utils_kb import (
    contact_keyboard,
    reg_confirm_kb,
    reg_edit_name_back_kb,
    reg_guide_kb,
    reg_name_conflict_kb,
)
from bot.loader import get_bot
from bot.services.client.client_notifications import ClientNotificationService
from bot.services.utils.auth import AuthService
from bot.services.utils.registration import RegistrationService
from bot.states.register_states import RegisterStates
from bot.utils.commands import admin_commands, client_commands
from bot.utils.info import (
    show_main_admin_menu,
    show_main_client_menu,
)
from bot.utils.role import RoleFilter, Role
from bot.utils.tools import normalize_phone
from bot.validators.validators import FULL_NAME_PATTERN


def create_reg_router(
        user_repo, clinic_repo, staff_repo, client_notification_service: ClientNotificationService,
        user_settings_repo,
        client_clinic_repo=None,
) -> Router:
    # Language lookup is two-regime: registered users read current_user.language
    # (populated by UserContextMiddleware on every message/callback, see
    # bot/middlewares/user.py and its wiring in bot/run.py). Users still inside
    # RegisterStates (language not persisted yet) read (await state.get_data())["language"].
    router = Router()
    reg = RegistrationService(
        user_repo, clinic_repo, user_settings_repo, client_clinic_repository=client_clinic_repo,
    )

    auth = AuthService(staff_repo)

    # ---------- /start ----------

    @router.message(CommandStart(), RoleFilter(None))
    async def start_guest(
            message: Message,
            state: FSMContext,
            command: CommandObject,
    ):
        # Each bot instance now serves exactly one clinic, so an outdated,
        # mismatched, or missing token (older QR codes / share links) still
        # resolves correctly -- as long as this database has exactly one
        # clinic. A matching token is still preferred when present.
        clinic = await reg.resolve_start_clinic(command.args)

        if clinic is None:
            await message.answer(msg.INVALID_CLINIC_TOKEN)
            return

        await state.clear()

        await state.update_data(
            clinic_id=clinic.clinic_id,
            clinic_name=clinic.name,
        )

        await state.set_state(RegisterStates.language)
        await message.answer(msg.CHOOSE_LANGUAGE_PROMPT, reply_markup=language_kb())

    @router.callback_query(RegisterStates.language, LanguageCB.filter())
    async def choose_language(callback: CallbackQuery, callback_data: LanguageCB, state: FSMContext):
        lang = callback_data.value
        await state.update_data(language=lang)
        await state.set_state(RegisterStates.phone)
        await callback.answer('')
        await callback.message.answer(msg.registration_intro(lang), reply_markup=reg_guide_kb())
        await callback.message.answer(msg.send_contact_prompt(lang), reply_markup=contact_keyboard())

    @router.callback_query(F.data == "reg_guide")
    async def show_registration_guide(callback: CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        lang = data.get("language", "ru")
        await callback.message.edit_text(msg.registration_guide(lang), reply_markup=None)
        await callback.answer()

    # ---------- registration ----------

    @router.message(RegisterStates.phone, F.contact)
    async def get_phone(message: Message, state: FSMContext):

        data = await state.get_data()
        lang = data.get("language", "ru")
        phone = normalize_phone(phone=message.contact.phone_number)

        try:
            result = await reg.check_phone(
                phone, message.from_user.id, contact_user_id=message.contact.user_id,
            )
        except UserAlreadyExistsError:
            await message.answer(msg.already_registered(lang))
            return
        except PhoneAlreadyExistsError:
            await message.answer(msg.phone_already_linked(lang))
            return
        except ContactOwnershipMismatchError:
            await message.answer(msg.contact_ownership_mismatch(lang))
            return

        await state.update_data(phone=phone)

        if result.status == "found_unclaimed":
            await state.update_data(
                existing_user_id=result.existing_user.ID,
                existing_full_name=result.existing_user.full_name,
            )
            await state.set_state(RegisterStates.name_conflict)
            await message.answer(
                msg.existing_user_found_prompt(result.existing_user.full_name, lang),
                reply_markup=reg_name_conflict_kb(),
            )
            return

        await state.set_state(RegisterStates.full_name)
        await message.answer(msg.full_name_prompt(lang))

    @router.message(RegisterStates.full_name, F.text)
    async def get_full_name(message: Message, state: FSMContext):
        lang = (await state.get_data()).get("language", "ru")

        if not await full_name_processing(
                message, state, next_state=RegisterStates.birth_date, re_pattern=FULL_NAME_PATTERN, lang=lang):
            return

        data = await state.get_data()
        existing_user_id = data.get("existing_user_id")

        if existing_user_id is not None:
            await reg.apply_name_conflict_resolution(existing_user_id, data["full_name"])

            await client_notification_service.notify_admins_name_changed_on_registration(
                data["clinic_id"], data["existing_full_name"], data["full_name"], data["phone"],
            )

        await message.answer(msg.birth_date_prompt(lang))

    @router.callback_query(RegisterStates.name_conflict, F.data == "reg_name_conflict_yes")
    async def confirm_name_conflict_yes(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        lang = data.get("language", "ru")
        await state.set_state(RegisterStates.full_name)
        await callback.answer('')
        await callback.message.answer(msg.full_name_prompt(lang))

    @router.callback_query(RegisterStates.name_conflict, F.data == "reg_name_conflict_no")
    async def confirm_name_conflict_no(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        lang = data.get("language", "ru")

        await state.update_data(full_name=data["existing_full_name"])
        await state.set_state(RegisterStates.birth_date)
        await callback.answer('')
        await callback.message.answer(msg.birth_date_prompt(lang))

    @router.message(RegisterStates.birth_date, F.text)
    async def get_birth_date(message: Message, state: FSMContext):
        lang = (await state.get_data()).get("language", "ru")
        if not await birth_date_processing(message, state, next_state=RegisterStates.gender, lang=lang):
            return
        await message.answer(msg.gender_prompt(lang), reply_markup=gender_kb())

    @router.callback_query(RegisterStates.gender, GenderCB.filter())
    async def choose_gender(callback: CallbackQuery, callback_data: GenderCB, state: FSMContext):
        await state.update_data(gender=callback_data.value)
        await state.set_state(RegisterStates.confirm_register)
        await callback.answer('')
        lang = (await state.get_data()).get("language", "ru")
        await show_confirmation(callback.message, state, reg_confirm_kb(), lang=lang)

    @router.callback_query(
        RegisterStates.confirm_register,
        F.data == "reg_edit"
    )
    async def edit_name(callback: CallbackQuery, state: FSMContext):
        lang = (await state.get_data()).get("language", "ru")
        await edit_full_name(
            callback, state, RegisterStates.edit_full_name, reply_markup=reg_edit_name_back_kb(), lang=lang,
        )

    @router.message(
        RegisterStates.edit_full_name, F.text)
    async def process_full_name_edition(message: Message, state: FSMContext):
        lang = (await state.get_data()).get("language", "ru")
        if not await full_name_processing(
                message, state, next_state=RegisterStates.confirm_register, re_pattern=FULL_NAME_PATTERN, lang=lang):
            return
        await show_confirmation(message, state, reg_confirm_kb(), lang=lang)

    @router.callback_query(RegisterStates.edit_full_name, F.data == "reg_edit_name_back")
    async def back_from_full_name_edition(callback: CallbackQuery, state: FSMContext):
        await state.set_state(RegisterStates.confirm_register)
        await callback.answer('')
        data = await state.get_data()
        lang = data.get("language", "ru")
        await show_confirmation(callback.message, state, reg_confirm_kb(), lang=lang)

    @router.callback_query(RegisterStates.confirm_register, F.data == "reg_confirm")
    async def final_reg(callback: CallbackQuery, state: FSMContext):

        data = await state.get_data()
        lang = data.get("language", "ru")

        role = await auth.detect_role(
            telegram_user_id=callback.from_user.id,
            clinic_id=data["clinic_id"],
        )

        try:
            await reg.register(
                telegram_user_id=callback.from_user.id,
                full_name=data["full_name"],
                phone=data["phone"],
                role=role,
                clinic_id=data["clinic_id"],
                existing_user_id=data.get("existing_user_id"),
                birth_date=data.get("birth_date"),
                gender=data.get("gender"),
                language=lang,
            )
        except UserAlreadyExistsError:
            await callback.message.answer(msg.already_registered(lang))
            await callback.answer()
            return
        except PhoneAlreadyExistsError:
            await callback.message.answer(msg.phone_already_linked(lang))
            await callback.answer()
            return

        await callback.message.answer(msg.registration_success(lang))

        bot = get_bot()

        if role == Role.ADMIN:
            await show_main_admin_menu(callback.message, full_name=data["full_name"], lang=lang)
            await bot.set_my_commands(admin_commands(lang), scope=BotCommandScopeChat(chat_id=callback.from_user.id))
        else:
            await show_main_client_menu(
                callback.message, full_name=data["full_name"], clinic_name=data["clinic_name"], lang=lang,
            )
            await bot.set_my_commands(client_commands(lang), scope=BotCommandScopeChat(chat_id=callback.from_user.id))

        await callback.answer()
        await state.clear()

    return router
