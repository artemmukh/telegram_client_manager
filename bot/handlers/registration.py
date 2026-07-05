from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from bot.handlers.utils.admin_utils.confirmations import show_confirmation
from bot.handlers.utils.admin_utils.input_helpers import (
    edit_full_name,
    process_edit_full_name, full_name_processing

)
from bot.keyboards.utils.utils_kb import contact_keyboard, reg_confirm_kb

from bot.services.utils.auth import AuthService
from bot.services.utils.registration import RegistrationService
from bot.states.register_states import RegisterStates
from bot.utils.info import (
    show_main_admin_menu,
    show_main_client_menu,
)
from aiogram.filters import CommandStart, CommandObject
from bot.utils.role import RoleFilter, Role
from bot.utils.tools import normalize_phone
from bot.validators.validators import FULL_NAME_PATTERN


def create_reg_router(user_repo, clinic_repo, staff_repo) -> Router:
    router = Router()
    reg = RegistrationService(user_repo)

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
            await message.answer("Пожалуйста, отсканируйте QR-код клиники.")
            return

        clinic = await clinic_repo.get_clinic_by_token(token)

        if clinic is None:
            await message.answer("QR-код недействителен.")
            return

        await state.update_data(
            clinic_id=clinic.clinic_id,
            clinic_name=clinic.name,
        )

        await message.answer("Пройдите регистрацию для дальнейшего взаимодействия.")
        await state.set_state(RegisterStates.full_name)
        await message.answer("Отправьте ФИО: ")

    # ---------- registration ----------

    @router.message(RegisterStates.full_name)
    async def get_full_name(message: Message, state: FSMContext):


        if not await full_name_processing(message, state, next_state=RegisterStates.phone, re_pattern=FULL_NAME_PATTERN):
            return

        await message.answer("Отправьте ваш контакт: ", reply_markup=contact_keyboard())

    @router.message(RegisterStates.phone, F.contact)
    async def get_phone(message: Message, state: FSMContext):

        await state.update_data(phone=normalize_phone(phone=message.contact.phone_number))

        await state.set_state(RegisterStates.confirm_register)

        await show_confirmation(message, state, reg_confirm_kb())

    @router.callback_query(
        RegisterStates.confirm_register,
        F.data == "reg_edit"
    )
    async def edit_name(callback: CallbackQuery, state: FSMContext):
        await edit_full_name(callback, state, RegisterStates.edit_full_name)

    @router.message(
        RegisterStates.edit_full_name, F.text)
    async def process_full_name_edition(message: Message, state: FSMContext):
        if not await process_edit_full_name(

                message, state, final_state=RegisterStates.confirm_register, re_pattern=FULL_NAME_PATTERN):
            return
        await show_confirmation(message, state, reg_confirm_kb())

    @router.callback_query(RegisterStates.confirm_register, F.data == "reg_confirm")
    async def final_reg(callback: CallbackQuery, state: FSMContext):

        data = await state.get_data()

        role = await auth.detect_role(
            telegram_user_id=callback.from_user.id,
            clinic_id=data["clinic_id"],
        )

        await reg.register(
            telegram_user_id=callback.from_user.id,
            full_name=data["full_name"],
            phone=data["phone"],
            role=role,
            clinic_id=data["clinic_id"],
        )
        await callback.message.answer("Регистрация прошла успешно!")

        if role == Role.ADMIN:
            await show_main_admin_menu(callback.message, full_name=data["full_name"])
        else:
            await show_main_client_menu(callback.message, full_name=data["full_name"])

        await callback.answer()
        await state.clear()

    return router
