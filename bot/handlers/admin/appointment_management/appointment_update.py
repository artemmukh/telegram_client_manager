from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError
from bot.handlers.utils.admin_utils.appointment_helpers import (
    build_appointment_card,
    show_appointments_with_actions,
)
from bot.handlers.utils.admin_utils.input_helpers import phone_processing
from bot.keyboards.admin.record_management_kb.appointment_kb import appointment_update_menu_kb
from bot.keyboards.utils.utils_kb import cancel_kb
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_scheduler import AppointmentScheduler
from bot.states.admin.record_management.appointment_states import AppointmentUpdateStates
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.role import RoleFilter


def create_admin_appointment_update_router(
    appointment_repo, user_repo, staff_repo, clinic_repo, scheduler=None
):
    router = Router()

    appt_mng = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    @router.callback_query(F.data == "update_record")
    async def start_update(callback_query: CallbackQuery, state: FSMContext):
        await state.set_state(AppointmentUpdateStates.client_phone)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите номер телефона клиента:",
            reply_markup=cancel_kb(),
        )

    @router.message(AppointmentUpdateStates.client_phone, F.text)
    async def process_phone(message: Message, state: FSMContext):
        if not await phone_processing(
            message, state, final_state=AppointmentUpdateStates.proceed
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

        await show_appointments_with_actions(
            message, data["phone"], appointments, appointment_update_menu_kb
        )

    @router.callback_query(AppointmentUpdateStates.proceed, F.data.startswith("appt_status:"))
    async def change_status(callback_query: CallbackQuery, state: FSMContext):
        _, appointment_id, status_value = callback_query.data.split(":")
        appointment_id = int(appointment_id)

        try:
            appointment = await appt_mng.update_status(
                appointment_id, AppointmentStatus(status_value)
            )
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        # Cancel reminders when status changes (no longer needed for non-PENDING/CONFIRMED)
        if scheduler:
            await scheduler.cancel_appointment_reminders(appointment_id)

            # Cancel completion job if status is now CANCELLED/NO_SHOW/COMPLETED
            new_status = AppointmentStatus(status_value)
            if new_status in (
                AppointmentStatus.CANCELLED,
                AppointmentStatus.NO_SHOW,
                AppointmentStatus.COMPLETED,
            ):
                await scheduler.cancel_appointment_completions(appointment_id)
            # Reschedule completion if status changed back to PENDING/CONFIRMED
            elif new_status in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED):
                await scheduler.schedule_appointment_completion(appointment)

        await callback_query.answer("Статус обновлён")
        await callback_query.message.edit_text(
            build_appointment_card(appointment),
            reply_markup=appointment_update_menu_kb(appointment.id),
        )

    @router.callback_query(AppointmentUpdateStates.proceed, F.data.startswith("appt_edit_dt:"))
    async def start_edit_datetime(callback_query: CallbackQuery, state: FSMContext):
        appointment_id = int(callback_query.data.split(":")[1])
        await state.update_data(appointment_id=appointment_id)
        await state.set_state(AppointmentUpdateStates.new_datetime)
        await callback_query.answer('')
        await callback_query.message.answer(
            "Введите новую дату и время (ГГГГ-ММ-ДД ЧЧ:ММ):",
            reply_markup=cancel_kb(),
        )

    @router.message(AppointmentUpdateStates.new_datetime, F.text)
    async def process_new_datetime(message: Message, state: FSMContext):
        data = await state.get_data()
        appointment_id = data["appointment_id"]

        try:
            appointment = await appt_mng.update_datetime(appointment_id, message.text.strip())
        except ValidationError as e:
            await message.answer(str(e))
            return
        except BotException as e:
            await message.answer(f"Ошибка обновления: {e}")
            return

        # Reschedule reminders and completion with new datetime
        if scheduler:
            await scheduler.cancel_appointment_reminders(appointment_id)
            await scheduler.schedule_appointment_reminders(appointment)
            await scheduler.cancel_appointment_completions(appointment_id)
            await scheduler.schedule_appointment_completion(appointment)

        await state.set_state(AppointmentUpdateStates.proceed)
        await message.answer(
            "Время обновлено.\n\n" + build_appointment_card(appointment),
            reply_markup=appointment_update_menu_kb(appointment.id),
        )

    @router.callback_query(AppointmentUpdateStates.proceed, F.data.startswith("appt_edit_purpose:"))
    async def start_edit_purpose(callback_query: CallbackQuery, state: FSMContext):
        appointment_id = int(callback_query.data.split(":")[1])
        await state.update_data(appointment_id=appointment_id)
        await state.set_state(AppointmentUpdateStates.new_purpose)
        await callback_query.answer('')
        await callback_query.message.answer(
            "Введите новое описание услуги:",
            reply_markup=cancel_kb(),
        )

    @router.message(AppointmentUpdateStates.new_purpose, F.text)
    async def process_new_purpose(message: Message, state: FSMContext):
        data = await state.get_data()

        try:
            appointment = await appt_mng.update_purpose(data["appointment_id"], message.text.strip())
        except ValidationError as e:
            await message.answer(str(e))
            return
        except BotException as e:
            await message.answer(f"Ошибка обновления: {e}")
            return

        await state.set_state(AppointmentUpdateStates.proceed)
        await message.answer(
            "Услуга обновлена.\n\n" + build_appointment_card(appointment),
            reply_markup=appointment_update_menu_kb(appointment.id),
        )

    return router
