from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.user_exceptions import InvalidFullNameError
from bot.handlers.utils.utils import show_confirmation
from bot.keyboards.utils.utils_kb import contact_keyboard, reg_confirm_kb
from bot.services.utils.auth import AuthService
from bot.services.utils.registration import RegistrationService
from bot.states.register_states import RegisterStates
from bot.states.utils.client_edit_states import EditStates
from bot.utils.info import (
    display_admin_help_msg,
    display_client_help_msg,
    show_main_admin_menu,
    show_main_client_menu,
)
from bot.utils.role import RoleFilter, Role
from bot.utils.tools import normalize_phone
from bot.validators.validators import validate_full_name


def create_main_router(user_repo) -> Router:
    router = Router()
    reg = RegistrationService(user_repo)

    # ---------- /start ----------

    @router.message(F.text == "/start", RoleFilter("admin"))
    async def start_admin(message: Message, state: FSMContext):
        await state.clear()
        await show_main_admin_menu(message)

    @router.message(F.text == "/start", RoleFilter("client"))
    async def start_client(message: Message, state: FSMContext):
        await state.clear()
        await show_main_client_menu(message)

    @router.message(F.text == "/start", RoleFilter(None))  # not registered
    async def start_guest(message: Message, state: FSMContext):
        await message.answer("Пройдите регистрацию для дальнейшего взаимодействия.")
        await state.set_state(RegisterStates.full_name)
        await message.answer("Отправьте ФИО: ")

    # ---------- registration ----------

    @router.message(RegisterStates.full_name)
    async def get_full_name(message: Message, state: FSMContext):
        full_name = message.text.strip()
        try:
            validate_full_name(full_name)
        except InvalidFullNameError as e:
            await message.answer(str(e))
            return

        await state.update_data(full_name=full_name)

        await state.set_state(RegisterStates.phone)

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

        await state.set_state(EditStates.edit_full_name)

        await callback.answer('')

        await callback.message.edit_text(
            "Введите новое ФИО:",
            reply_markup=None
        )

    @router.message(EditStates.edit_full_name)
    async def process_edit_full_name(message: Message, state: FSMContext):

        full_name = message.text.strip()

        try:
            validate_full_name(full_name)
        except InvalidFullNameError as e:
            await message.answer(str(e))
            return

        await state.update_data(full_name=full_name)

        await state.set_state(RegisterStates.confirm_register)

        await show_confirmation(message, state, reg_confirm_kb())

    @router.callback_query(RegisterStates.confirm_register, F.data == "reg_confirm")
    async def final_reg(callback: CallbackQuery, state: FSMContext):

        data = await state.get_data()

        role = AuthService.detect_role(callback.from_user.id)


        await reg.register(
            full_name=data["full_name"],
            phone=data["phone"],
            role=role,
            telegram_user_id=callback.from_user.id
        )
        await callback.message.answer("Регистрация прошла успешно!")

        if role == Role.ADMIN:
            await show_main_admin_menu(callback.message)
        else:
            await show_main_client_menu(callback.message)

        await callback.answer()
        await state.clear()

    # ---------- /help split by role ----------

    @router.message(F.text.in_({"/help", "❓ Справка"}), RoleFilter("admin"))
    async def help_admin(message: Message):
        await display_admin_help_msg(message)

    @router.message(F.text.in_({"/help", "❓ Справка"}), RoleFilter("client"))
    async def help_client(message: Message):
        await display_client_help_msg(message)

    # ---------- /profile ----------

    @router.message(F.text.in_({"/profile", "⚙️ Мой профиль"}))
    async def profile(message: Message):
        user = await user_repo.get_user_by_telegram_id(message.from_user.id)

        if user.role == "admin":
            role = "администратор"
        else:
            role = "клиент"

        await message.answer(
            "Профиль\n\n"
            f"ФИО: {user.full_name}\n"
            f"ID клиента: {user.ID}\n"
            f"Номер телефона: {user.phone}\n"
            f"Тип пользователя: {role}"
        )

    @router.callback_query(F.data == "cancel")
    async def cancel(callback: CallbackQuery, state: FSMContext):
        await state.clear()

        await callback.message.edit_text(
            "Действие отменено.",
            reply_markup=None
        )

        await callback.answer('')

    return router
