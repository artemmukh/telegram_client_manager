from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError
from bot.handlers.utils.admin_utils.appointment_helpers import (
    build_appointment_card,
    build_appointment_confirmation,
    client_name_processing,
    datetime_processing,
    purpose_processing,
)
from bot.handlers.utils.admin_utils.input_helpers import phone_processing
from bot.keyboards.admin.record_management_kb.appointment_kb import (
    appointment_confirm_kb,
    appointment_datetime_confirm_kb,
    client_creation_confirm_kb,
    back_to_records_kb,
)
from bot.keyboards.utils.utils_kb import cancel_kb
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_scheduler import AppointmentScheduler
from bot.states.admin.record_management.appointment_states import AppointmentCreationStates
from bot.utils.role import RoleFilter


def create_admin_appointment_creation_router(
    appointment_repo, user_repo, staff_repo, clinic_repo, notification_service=None, scheduler=None
):
    router = Router()

    appt_mng = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    @router.callback_query(F.data == "create_record")
    async def start_create(callback_query: CallbackQuery, state: FSMContext):
        try:
            clinic = await appt_mng.get_admin_clinic(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        await state.update_data(clinic_name=clinic.name)
        await state.set_state(AppointmentCreationStates.client_name)
        await callback_query.answer('')
        await callback_query.message.edit_text("Введите имя клиента:", reply_markup=cancel_kb())

    @router.callback_query(F.data == "restart_appointment_create")
    async def restart_create(callback_query: CallbackQuery, state: FSMContext):
        await state.set_state(AppointmentCreationStates.client_name)
        await callback_query.answer('')
        await callback_query.message.answer("Введите имя клиента:", reply_markup=cancel_kb())

    @router.message(AppointmentCreationStates.client_name, F.text)
    async def get_name(message: Message, state: FSMContext):
        if not await client_name_processing(message, state, AppointmentCreationStates.client_phone):
            return
        await message.answer("Введите номер телефона клиента:", reply_markup=cancel_kb())

    @router.message(AppointmentCreationStates.client_phone, F.text)
    async def get_phone(message: Message, state: FSMContext):
        if not await phone_processing(
            message, state, final_state=AppointmentCreationStates.client_creation_confirm
        ):
            return

        data = await state.get_data()
        phone = data.get('phone')

        client = await user_repo.get_client_by_phone(phone)

        if client:
            await state.set_state(AppointmentCreationStates.appointment_datetime)
            await message.answer(
                "Введите дату и время на русском языке:\n"
                "Например: завтра в 3 часа, 13 сентября 15:30, в понедельник в 14:00, сегодня в 18:00",
                reply_markup=cancel_kb(),
            )
        else:
            client_name = data.get('client_name')
            await message.answer(
                f"Клиент не найден.\n\n"
                f"Создать нового клиента?\n"
                f"Имя: {client_name}\n"
                f"Телефон: {phone}",
                reply_markup=client_creation_confirm_kb(),
            )

    @router.callback_query(AppointmentCreationStates.client_creation_confirm, F.data == "create_client")
    async def handle_create_client(callback_query: CallbackQuery, state: FSMContext):
        from bot.utils.role import Role

        data = await state.get_data()
        phone = data.get('phone')
        client_name = data.get('client_name')
        clinic = await appt_mng.get_admin_clinic(callback_query.from_user.id)

        from bot.models.user import User

        new_client = User(
            full_name=client_name,
            phone=phone,
            role=Role.CLIENT,
            clinic_id=clinic.clinic_id,
            clinic_name=clinic.name,
        )

        await user_repo.create_user(new_client)

        await state.set_state(AppointmentCreationStates.appointment_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите дату и время на русском языке:\n"
            "Например: завтра в 3 часа, 13 сентября 15:30, в понедельник в 14:00, сегодня в 18:00",
            reply_markup=cancel_kb(),
        )

    @router.callback_query(AppointmentCreationStates.client_creation_confirm, F.data == "cancel_client_creation")
    async def handle_cancel_client_creation(callback_query: CallbackQuery, state: FSMContext):
        await state.set_state(AppointmentCreationStates.client_phone)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите номер телефона клиента:",
            reply_markup=cancel_kb(),
        )

    @router.message(AppointmentCreationStates.appointment_datetime, F.text)
    async def get_datetime(message: Message, state: FSMContext):
        if not await datetime_processing(message, state, AppointmentCreationStates.appointment_datetime_confirm):
            return
        data = await state.get_data()
        await message.answer(
            f"Вы имели в виду: {data.get('appointment_datetime_display')}?",
            reply_markup=appointment_datetime_confirm_kb(),
        )

    @router.callback_query(AppointmentCreationStates.appointment_datetime_confirm, F.data == "approve_datetime")
    async def confirm_datetime(callback_query: CallbackQuery, state: FSMContext):
        from bot.services.date_parser import format_datetime_for_db

        data = await state.get_data()
        parsed_dt = data.get('appointment_datetime_parsed')

        if not parsed_dt:
            await callback_query.answer(
                "Ошибка: не удалось обработать дату. Попробуйте снова.",
                show_alert=True
            )
            await state.set_state(AppointmentCreationStates.appointment_datetime)
            return

        db_datetime = format_datetime_for_db(parsed_dt)
        await state.update_data(appointment_datetime=db_datetime)

        await state.set_state(AppointmentCreationStates.purpose)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Опишите услугу (например: Консультация, Чистка):",
            reply_markup=cancel_kb(),
        )

    @router.callback_query(AppointmentCreationStates.appointment_datetime_confirm, F.data == "retry_datetime")
    async def retry_datetime(callback_query: CallbackQuery, state: FSMContext):
        await state.set_state(AppointmentCreationStates.appointment_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Введите дату и время на русском языке:\n"
            "Например: завтра в 3 часа, 13 сентября 15:30, в понедельник в 14:00",
            reply_markup=cancel_kb(),
        )

    @router.message(AppointmentCreationStates.purpose, F.text)
    async def get_purpose(message: Message, state: FSMContext):
        if not await purpose_processing(message, state, AppointmentCreationStates.confirm):
            return
        data = await state.get_data()
        await message.answer(
            build_appointment_confirmation(data),
            reply_markup=appointment_confirm_kb(),
        )

    @router.callback_query(AppointmentCreationStates.confirm, F.data == "approve_appointment_create")
    async def finish(callback_query: CallbackQuery, state: FSMContext):
        data = await state.get_data()

        try:
            appointment = await appt_mng.create_appointment(callback_query.from_user.id, data)
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка создания записи: {e}", show_alert=True)
            return

        # Send notification to client if notification service is available
        notification_text = "Запись успешно создана!\n\n" + build_appointment_card(appointment)
        if notification_service:
            notification_sent = await notification_service.notify_client_appointment(appointment)
            if notification_sent:
                notification_text += "\n✅ Уведомление отправлено клиенту"
            else:
                notification_text += "\n⚠️ Не удалось отправить уведомление клиенту (нет Telegram ID)"

        # Schedule reminders if scheduler is available
        if scheduler:
            await scheduler.schedule_appointment_reminders(appointment)
            notification_text += "\n⏰ Напоминания запланированы (24ч и 2ч перед приемом)"

        # Schedule completion if scheduler is available
        if scheduler:
            await scheduler.schedule_appointment_completion(appointment)
            notification_text += "\n✅ Автозавершение: через 1ч после приема"

        await callback_query.message.edit_text(
            notification_text,
            reply_markup=back_to_records_kb(),
        )
        await state.clear()

    return router
