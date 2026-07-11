from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.exceptions import BotException
from bot.handlers.utils.admin_utils.input_helpers import full_name_processing
from bot.keyboards.admin.name_change_kb import name_change_approval_kb
from bot.models.user import User
from bot.services.client.client_management import ClientManagement
from bot.services.client.client_notifications import ClientNotificationService
from bot.states.name_change_states import NameChangeStates
from bot.utils.role import RoleFilter
from bot.validators.validators import FULL_NAME_PATTERN


def create_name_change_request_router(
        client_management_service: ClientManagement,
        client_notification_service: ClientNotificationService,
) -> Router:
    router = Router()

    router.message.filter(RoleFilter("*"))
    router.callback_query.filter(RoleFilter("*"))

    @router.callback_query(F.data == "profile_change_name")
    async def start_name_change(callback_query: CallbackQuery, state: FSMContext):
        await state.set_state(NameChangeStates.entering_name)
        await callback_query.answer('')
        await callback_query.message.answer(
            "👤 Введите ваше новое ФИО.\n\n"
            "Пожалуйста, используйте реальные данные.\n"
            "Они будут отображаться врачу во время записи на приём."
        )

    @router.message(NameChangeStates.entering_name, F.text)
    async def process_name_change(message: Message, state: FSMContext, current_user: User | None = None):
        if not await full_name_processing(
                message, state, next_state=NameChangeStates.entering_name, re_pattern=FULL_NAME_PATTERN):
            return

        data = await state.get_data()
        new_full_name = data["full_name"]

        try:
            user = await client_management_service.request_name_change(current_user.ID, new_full_name)
        except BotException as e:
            await message.answer(str(e))
            return

        await client_notification_service.notify_admins_name_change_request(
            user, new_full_name, reply_markup=name_change_approval_kb(user.ID),
        )

        await message.answer("✅ Запрос на смену ФИО отправлен администратору клиники. Ожидайте решения.")
        await state.clear()

    return router
