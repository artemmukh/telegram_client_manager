from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError
from bot.handlers.utils.admin_utils.appointment_helpers import show_appointments_with_actions
from bot.handlers.utils.admin_utils.input_helpers import phone_processing
from bot.keyboards.admin.record_management_kb.appointment_kb import (
    appointment_delete_confirm_kb,
    back_to_records_kb,
    choose_appointment_to_delete_kb,
)
from bot.keyboards.utils.utils_kb import cancel_kb
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_scheduler import AppointmentScheduler
from bot.states.admin.record_management.appointment_states import AppointmentDeletionStates
from bot.utils.role import RoleFilter


def create_admin_appointment_deletion_router(
    appointment_repo, user_repo, staff_repo, clinic_repo, scheduler=None
):
    router = Router()

    appt_mng = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    @router.callback_query(F.data == "delete_record")
    async def start_delete(callback_query: CallbackQuery, state: FSMContext):
        await state.set_state(AppointmentDeletionStates.client_phone)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите номер телефона клиента:",
            reply_markup=cancel_kb(),
        )

    @router.message(AppointmentDeletionStates.client_phone, F.text)
    async def process_phone(message: Message, state: FSMContext):
        if not await phone_processing(
            message, state, final_state=AppointmentDeletionStates.proceed
        ):
            return

        data = await state.get_data()

        try:
            appointments = await appt_mng.search_appointments(data)
        except ValidationError as e:
            await message.answer(str(e))
            await state.clear()
            return
        except BotException as e:
            await message.answer(f"Ошибка поиска: {e}")
            await state.clear()
            return

        await show_appointments_with_actions(
            message, data["phone"], appointments, choose_appointment_to_delete_kb
        )

    @router.callback_query(AppointmentDeletionStates.proceed, F.data.startswith("appt_delete:"))
    async def choose(callback_query: CallbackQuery, state: FSMContext):
        appointment_id = int(callback_query.data.split(":")[1])
        await callback_query.answer('')
        await callback_query.message.edit_reply_markup(
            reply_markup=appointment_delete_confirm_kb(appointment_id)
        )

    @router.callback_query(
        AppointmentDeletionStates.proceed, F.data.startswith("appt_approve_delete:")
    )
    async def finish(callback_query: CallbackQuery, state: FSMContext):
        appointment_id = int(callback_query.data.split(":")[1])

        try:
            await appt_mng.delete_appointment(appointment_id)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        # Cancel reminders and completion when appointment is deleted
        if scheduler:
            await scheduler.cancel_appointment_reminders(appointment_id)
            await scheduler.cancel_appointment_completions(appointment_id)

        await callback_query.message.edit_text("Запись удалена.", reply_markup=back_to_records_kb())
        await state.clear()

    return router
