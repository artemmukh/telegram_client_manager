from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.exceptions.exceptions import BotException
from bot.handlers.common.profile import build_profile_text
from bot.handlers.utils.admin_utils.input_helpers import birth_date_processing
from bot.keyboards.common.profile_kb import profile_menu_kb, profile_personal_data_kb
from bot.keyboards.utils.gender_cb import GenderCB
from bot.keyboards.utils.gender_kb import gender_kb
from bot.models.user import User
from bot.services.client.client_management import ClientManagement
from bot.states.profile_personal_data_states import ProfilePersonalDataStates
from bot.utils.role import RoleFilter

BIRTH_DATE_PROMPT = "Введите дату рождения в формате ДД.ММ.ГГГГ, например 05.03.1990:"

_BACK_TO_PERSONAL_DATA_KB = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="profile_personal_data")]]
)


def create_personal_data_router(client_management_service: ClientManagement) -> Router:
    router = Router()

    router.message.filter(RoleFilter("*"))
    router.callback_query.filter(RoleFilter("*"))

    @router.callback_query(F.data == "profile_personal_data")
    async def open_personal_data(callback_query: CallbackQuery, state: FSMContext, current_user: User | None = None):
        await state.clear()
        await callback_query.answer()
        try:
            await callback_query.message.edit_text(
                build_profile_text(current_user, current_user.language), reply_markup=profile_personal_data_kb()
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise

    @router.callback_query(F.data == "profile_add_birth_date")
    async def start_add_birth_date(callback_query: CallbackQuery, state: FSMContext):
        await state.set_state(ProfilePersonalDataStates.birth_date)
        await callback_query.answer()
        try:
            await callback_query.message.edit_text(BIRTH_DATE_PROMPT, reply_markup=_BACK_TO_PERSONAL_DATA_KB)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise

    @router.message(ProfilePersonalDataStates.birth_date, F.text)
    async def process_birth_date(message: Message, state: FSMContext):
        if not await birth_date_processing(message, state, next_state=ProfilePersonalDataStates.gender):
            return
        await message.answer("Укажите пол:", reply_markup=gender_kb())

    @router.callback_query(ProfilePersonalDataStates.gender, GenderCB.filter())
    async def choose_gender(
        callback_query: CallbackQuery,
        callback_data: GenderCB,
        state: FSMContext,
        current_user: User | None = None,
    ):
        data = await state.get_data()

        try:
            updated_user = await client_management_service.update_personal_data(
                current_user.ID, birth_date=data.get("birth_date"), gender=callback_data.value,
            )
        except BotException as e:
            await state.set_state(ProfilePersonalDataStates.birth_date)
            await callback_query.answer()
            try:
                await callback_query.message.edit_text(
                    f"{e}\n\n{BIRTH_DATE_PROMPT}", reply_markup=_BACK_TO_PERSONAL_DATA_KB
                )
            except TelegramBadRequest as edit_error:
                if "message is not modified" not in str(edit_error):
                    raise
            return

        await state.clear()
        await callback_query.answer("Данные обновлены")
        try:
            await callback_query.message.edit_text(
                build_profile_text(updated_user, updated_user.language), reply_markup=profile_menu_kb()
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise

    return router
