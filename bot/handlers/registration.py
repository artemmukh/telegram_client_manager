from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, BotCommandScopeChat

from bot.exceptions.user_exceptions import ContactOwnershipMismatchError, PhoneAlreadyExistsError, \
    UserAlreadyExistsError
from bot.handlers.utils.admin_utils.confirmations import show_confirmation
from bot.handlers.utils.admin_utils.input_helpers import (
    birth_date_processing, edit_full_name, full_name_processing

)
from bot.keyboards.utils.gender_cb import GenderCB
from bot.keyboards.utils.gender_kb import gender_kb
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
from bot.utils.commands import ADMIN_COMMANDS, CLIENT_COMMANDS
from bot.utils.info import (
    display_registration_guide_msg,
    show_main_admin_menu,
    show_main_client_menu,
)
from bot.utils.role import RoleFilter, Role
from bot.utils.tools import normalize_phone
from bot.validators.validators import FULL_NAME_PATTERN

BIRTH_DATE_PROMPT = "Введите дату рождения в формате ДД.ММ.ГГГГ, например 05.03.1990:"


def create_reg_router(
        user_repo, clinic_repo, staff_repo, client_notification_service: ClientNotificationService,
        client_clinic_repo=None,
) -> Router:
    router = Router()
    reg = RegistrationService(user_repo, clinic_repo, client_clinic_repository=client_clinic_repo)

    auth = AuthService(staff_repo)

    # ---------- /start ----------

    @router.message(CommandStart(), RoleFilter(None))
    async def start_guest(
            message: Message,
            state: FSMContext,
            command: CommandObject,
    ):
        token = command.args

        if not token:
            await message.answer("Пожалуйста, отсканируйте QR-код клиники или воспользуйтесь пригласительной ссылкой.")
            return

        clinic = await reg.get_clinic_by_token(token)

        if clinic is None:
            await message.answer("QR-код недействителен.")
            return

        await state.clear()

        await state.update_data(
            clinic_id=clinic.clinic_id,
            clinic_name=clinic.name,
        )

        await message.answer("Пройдите регистрацию для дальнейшего взаимодействия.", reply_markup=reg_guide_kb())
        await state.set_state(RegisterStates.phone)
        await message.answer("Отправьте ваш контакт: ", reply_markup=contact_keyboard())

    @router.callback_query(F.data == "reg_guide")
    async def show_registration_guide(callback: CallbackQuery) -> None:
        await callback.message.edit_text(display_registration_guide_msg(), reply_markup=None)
        await callback.answer()

    # ---------- registration ----------

    @router.message(RegisterStates.phone, F.contact)
    async def get_phone(message: Message, state: FSMContext):

        phone = normalize_phone(phone=message.contact.phone_number)

        try:
            result = await reg.check_phone(
                phone, message.from_user.id, contact_user_id=message.contact.user_id,
            )
        except UserAlreadyExistsError:
            await message.answer("Вы уже зарегистрированы.")
            return
        except PhoneAlreadyExistsError:
            await message.answer(
                "Этот номер телефона уже привязан к другому аккаунту Telegram.\n"
                "Обратитесь в клинику."
            )
            return
        except ContactOwnershipMismatchError:
            await message.answer(
                "Похоже, вы отправили чужой контакт.\n"
                "Пожалуйста, отправьте свой собственный контакт кнопкой ниже."
            )
            return

        await state.update_data(phone=phone)

        if result.status == "found_unclaimed":
            await state.update_data(
                existing_user_id=result.existing_user.ID,
                existing_full_name=result.existing_user.full_name,
            )
            await state.set_state(RegisterStates.name_conflict)
            await message.answer(
                f"Вы были занесены как: {result.existing_user.full_name}\n\n"
                "Хотели бы вы изменить это?",
                reply_markup=reg_name_conflict_kb(),
            )
            return

        await state.set_state(RegisterStates.full_name)
        await message.answer(
            "👤 Введите ваше настоящее ФИ.\n\n"
            "Пожалуйста, используйте реальные данные.\n"
            "Они будут отображаться врачу во время записи на приём."
        )

    @router.message(RegisterStates.full_name, F.text)
    async def get_full_name(message: Message, state: FSMContext):

        if not await full_name_processing(
                message, state, next_state=RegisterStates.birth_date, re_pattern=FULL_NAME_PATTERN):
            return

        data = await state.get_data()
        existing_user_id = data.get("existing_user_id")

        if existing_user_id is not None:
            await reg.apply_name_conflict_resolution(existing_user_id, data["full_name"])

            await client_notification_service.notify_admins_name_changed_on_registration(
                data["clinic_id"], data["existing_full_name"], data["full_name"], data["phone"],
            )

        await message.answer(BIRTH_DATE_PROMPT)

    @router.callback_query(RegisterStates.name_conflict, F.data == "reg_name_conflict_yes")
    async def confirm_name_conflict_yes(callback: CallbackQuery, state: FSMContext):
        await state.set_state(RegisterStates.full_name)
        await callback.answer('')
        await callback.message.answer(
            "👤 Введите ваше настоящее ФИ.\n\n"
            "Пожалуйста, используйте реальные данные.\n"
            "Они будут отображаться врачу во время записи на приём."
        )

    @router.callback_query(RegisterStates.name_conflict, F.data == "reg_name_conflict_no")
    async def confirm_name_conflict_no(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()

        await state.update_data(full_name=data["existing_full_name"])
        await state.set_state(RegisterStates.birth_date)
        await callback.answer('')
        await callback.message.answer(BIRTH_DATE_PROMPT)

    @router.message(RegisterStates.birth_date, F.text)
    async def get_birth_date(message: Message, state: FSMContext):
        if not await birth_date_processing(message, state, next_state=RegisterStates.gender):
            return
        await message.answer("Укажите пол:", reply_markup=gender_kb())

    @router.callback_query(RegisterStates.gender, GenderCB.filter())
    async def choose_gender(callback: CallbackQuery, callback_data: GenderCB, state: FSMContext):
        await state.update_data(gender=callback_data.value)
        await state.set_state(RegisterStates.confirm_register)
        await callback.answer('')
        await show_confirmation(callback.message, state, reg_confirm_kb())

    @router.callback_query(
        RegisterStates.confirm_register,
        F.data == "reg_edit"
    )
    async def edit_name(callback: CallbackQuery, state: FSMContext):
        await edit_full_name(callback, state, RegisterStates.edit_full_name, reply_markup=reg_edit_name_back_kb())

    @router.message(
        RegisterStates.edit_full_name, F.text)
    async def process_full_name_edition(message: Message, state: FSMContext):
        if not await full_name_processing(

                message, state, next_state=RegisterStates.confirm_register, re_pattern=FULL_NAME_PATTERN):
            return
        await show_confirmation(message, state, reg_confirm_kb())

    @router.callback_query(RegisterStates.edit_full_name, F.data == "reg_edit_name_back")
    async def back_from_full_name_edition(callback: CallbackQuery, state: FSMContext):
        await state.set_state(RegisterStates.confirm_register)
        await callback.answer('')
        await show_confirmation(callback.message, state, reg_confirm_kb())

    @router.callback_query(RegisterStates.confirm_register, F.data == "reg_confirm")
    async def final_reg(callback: CallbackQuery, state: FSMContext):

        data = await state.get_data()

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
            )
        except UserAlreadyExistsError:
            await callback.message.answer("Вы уже зарегистрированы.")
            await callback.answer()
            return
        except PhoneAlreadyExistsError:
            await callback.message.answer(
                "Этот номер телефона уже привязан к другому аккаунту Telegram.\n"
                "Обратитесь в клинику."
            )
            await callback.answer()
            return

        await callback.message.answer("Регистрация прошла успешно!")

        bot = get_bot()

        if role == Role.ADMIN:
            await show_main_admin_menu(callback.message, full_name=data["full_name"])
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=callback.from_user.id))
        else:
            await show_main_client_menu(callback.message, full_name=data["full_name"])
            await bot.set_my_commands(CLIENT_COMMANDS, scope=BotCommandScopeChat(chat_id=callback.from_user.id))

        await callback.answer()
        await state.clear()

    return router
