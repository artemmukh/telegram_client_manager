from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError
from bot.handlers.utils.admin_utils.appointment_helpers import show_appointments_list
from bot.handlers.utils.admin_utils.input_helpers import phone_processing
from bot.keyboards.utils.utils_kb import cancel_kb
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.states.admin.record_management.appointment_states import AppointmentSearchStates
from bot.utils.role import RoleFilter


def create_admin_appointment_search_router(appointment_repo, user_repo, staff_repo, clinic_repo):
    router = Router()

    appt_mng = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    @router.callback_query(F.data == "search_record")
    async def start_search(callback_query: CallbackQuery, state: FSMContext):
        await state.set_state(AppointmentSearchStates.client_phone)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите номер телефона клиента:",
            reply_markup=cancel_kb(),
        )

    @router.message(AppointmentSearchStates.client_phone, F.text)
    async def process_search(message: Message, state: FSMContext):
        if not await phone_processing(
            message, state, final_state=AppointmentSearchStates.client_phone
        ):
            return

        data = await state.get_data()

        try:
            appointments = await appt_mng.search_appointments(data["phone"])
        except ValidationError as e:
            await message.answer(str(e))
            await state.clear()
            return
        except BotException as e:
            await message.answer(f"Ошибка поиска: {e}")
            await state.clear()
            return

        await show_appointments_list(message, data["phone"], appointments)
        await state.clear()

    return router
