from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from bot.exceptions.user_exceptions import InvalidFullNameError
from bot.keyboards.utils.utils_kb import contact_keyboard
from bot.services.utils.auth import AuthService
from bot.services.utils.registration import RegistrationService
from bot.validators.validators import validate_full_name
from bot.states.register_states import RegisterStates
from bot.utils.info import (
    display_admin_help_msg,
    display_client_help_msg,
    show_main_admin_menu,
    show_main_client_menu,
)
from bot.utils.role import RoleFilter, Role
from bot.utils.tools import normalize_phone


def create_main_router(user_repo) -> Router:
    router = Router()
    reg = RegistrationService(user_repo)

    # ---------- /start ----------

    @router.message(F.text == "/start", RoleFilter("client"))
    async def start_admin(message: Message, state: FSMContext):
        await state.clear()
        await show_main_admin_menu(message)

    @router.message(F.text == "/start", RoleFilter("record"))
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
    async def first_reg(message: Message, state: FSMContext):
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
    async def final_reg(message: Message, state: FSMContext):

        await state.update_data(phone=normalize_phone(phone = message.contact.phone_number))

        data = await state.get_data()

        role = AuthService.detect_role(message.from_user.id)


        await reg.register(
            full_name=data["full_name"],
            phone=data["phone"],
            role=role,
            telegram_user_id=message.from_user.id
        )
        await message.answer("Регистрация прошла успешно!")

        if role == Role.ADMIN:
            await show_main_admin_menu(message)
        else:
            await show_main_client_menu(message)

        await state.clear()


    # ---------- /help split by role ----------

    @router.message(F.text.in_({"/help", "❓ Справка"}), RoleFilter("client"))
    async def help_admin(message: Message):
        await display_admin_help_msg(message)

    @router.message(F.text.in_({"/help", "❓ Справка"}), RoleFilter("record"))
    async def help_client(message: Message):
        await display_client_help_msg(message)

    # ---------- /profile ----------

    @router.message(F.text.in_({"/profile", "⚙️ Мой профиль"}))
    async def profile(message: Message):
        user = await user_repo.get_user_by_telegram_id(message.from_user.id)

        if user.role == "client":
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

        await callback.answer()

    return router
