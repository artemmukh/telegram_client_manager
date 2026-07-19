from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError, PhoneAlreadyExistsError
from bot.handlers.utils.admin_utils import appointment_helpers as ah
from bot.handlers.utils.admin_utils.appointment_helpers import (
    DATETIME_INPUT_PROMPT,
    build_appointment_confirmation,
    build_appointment_card,
    datetime_processing,
    purpose_processing,
)
from bot.handlers.utils.admin_utils.confirmations import show_confirmation
from bot.handlers.utils.admin_utils.input_helpers import (
    ask_full_name,
    phone_processing,
    full_name_processing,
    edit_full_name,
    edit_phone,
)
from bot.keyboards.admin.record_management_kb.appointment_kb import (
    appointment_confirm_kb,
    appointment_datetime_confirm_kb,
    client_creation_confirm_kb,
    back_to_records_kb,
)
from bot.keyboards.client.booking_cb import ClientBookDoctorCB
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.utils.date_parser import format_datetime_for_db
from bot.states.admin.record_management.appointment_states import AppointmentCreationStates
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.role import RoleFilter
from bot.validators.validators import FULL_NAME_PATTERN, SEARCH_NAME_PATTERN


def create_admin_appointment_creation_router(
    appointment_repo, user_repo, staff_repo, clinic_repo, client_management=None, notification_service=None,
    scheduler=None, client_clinic_repo=None,
):
    router = Router()

    appt_mng = AppointmentManagement(
        appointment_repo, user_repo, staff_repo, clinic_repo, client_management,
        client_clinic_repository=client_clinic_repo,
    )

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    async def begin_appointment_creation(callback_query: CallbackQuery, state: FSMContext):
        await ah.begin_appointment_creation(appt_mng, callback_query, state)

    @router.callback_query(F.data == "create_record")
    async def start_create(callback_query: CallbackQuery, state: FSMContext):
        await begin_appointment_creation(callback_query, state)

    @router.callback_query(AppointmentCreationStates.choose_doctor, ClientBookDoctorCB.filter())
    async def pick_doctor(callback_query: CallbackQuery, callback_data: ClientBookDoctorCB, state: FSMContext):
        data = await state.get_data()
        staff_options = data.get("staff_options", {})
        staff_name = staff_options.get(str(callback_data.staff_user_id), "Врач")

        await state.update_data(staff_user_id=callback_data.staff_user_id, staff_name=staff_name)

        if data.get("client_preselected"):
            await state.set_state(AppointmentCreationStates.appointment_datetime)
            await callback_query.answer('')
            await callback_query.message.edit_text(DATETIME_INPUT_PROMPT, reply_markup=back_to_records_kb())
            return

        await ask_full_name(callback_query, state, AppointmentCreationStates.client_full_name, reply_markup=back_to_records_kb())

    @router.callback_query(F.data == "restart_appointment_create")
    async def restart_create(callback_query: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        if data.get("client_preselected"):
            await ah.begin_appointment_creation(
                appt_mng, callback_query, state,
                full_name=data.get("full_name"), phone=data.get("phone"),
                origin_client_id=data.get("origin_client_id"), origin_mode=data.get("origin_mode"),
                origin_page=data.get("origin_page"), origin_search_data=data.get("origin_search_data"),
            )
            return
        await begin_appointment_creation(callback_query, state)

    @router.message(AppointmentCreationStates.client_full_name, F.text)
    async def get_name(message: Message, state: FSMContext):
        if not await full_name_processing(message, state, AppointmentCreationStates.client_phone, re_pattern=SEARCH_NAME_PATTERN):
            return
        await message.answer("Введите номер телефона клиента:", reply_markup=back_to_records_kb())

    @router.message(AppointmentCreationStates.client_phone, F.text)
    async def get_phone(message: Message, state: FSMContext):
        if not await phone_processing(
            message, state, final_state=AppointmentCreationStates.confirm_create
        ):
            return

        data = await state.get_data()
        phone = data.get('phone')

        client = await appt_mng.find_client_by_phone(phone)

        if client:
            await state.set_state(AppointmentCreationStates.appointment_datetime)
            await message.answer(
                DATETIME_INPUT_PROMPT,
                reply_markup=back_to_records_kb(),
            )
        else:
            await show_confirmation(message, state, reply_markup=client_creation_confirm_kb())

    @router.callback_query(AppointmentCreationStates.confirm_create, F.data == "confirm_client_creation")
    async def handle_confirm_client_creation(callback_query: CallbackQuery, state: FSMContext):
        data = await state.get_data()

        try:
            await appt_mng.check_or_create_client(
                callback_query.from_user.id,
                full_name=data['full_name'],
                phone=data['phone'],
            )
        except PhoneAlreadyExistsError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка создания клиента: {e}", show_alert=True)
            return

        await state.set_state(AppointmentCreationStates.appointment_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            f"✅ Клиент создан: {data['full_name']}\n\n" + DATETIME_INPUT_PROMPT,
            reply_markup=back_to_records_kb(),
        )

    @router.callback_query(AppointmentCreationStates.confirm_create, F.data == "edit_client_name_in_appointment")
    async def handle_edit_client_name(callback_query: CallbackQuery, state: FSMContext):
        await edit_full_name(callback_query, state, AppointmentCreationStates.edit_full_name, reply_markup=back_to_records_kb())

    @router.message(AppointmentCreationStates.edit_full_name, F.text)
    async def process_edit_client_name(message: Message, state: FSMContext):
        if not await full_name_processing(message, state, AppointmentCreationStates.confirm_create, re_pattern=SEARCH_NAME_PATTERN):
            return
        await show_confirmation(message, state, reply_markup=client_creation_confirm_kb())

    @router.callback_query(AppointmentCreationStates.confirm_create, F.data == "edit_client_phone_in_appointment")
    async def handle_edit_client_phone(callback_query: CallbackQuery, state: FSMContext):
        await edit_phone(callback_query, state, AppointmentCreationStates.edit_phone, reply_markup=back_to_records_kb())

    @router.message(AppointmentCreationStates.edit_phone, F.text)
    async def process_edit_client_phone(message: Message, state: FSMContext):
        if not await phone_processing(
            message, state, final_state=AppointmentCreationStates.confirm_create
        ):
            return
        await show_confirmation(message, state, reply_markup=client_creation_confirm_kb())


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
            reply_markup=back_to_records_kb(),
        )

    @router.callback_query(AppointmentCreationStates.appointment_datetime_confirm, F.data == "retry_datetime")
    async def retry_datetime(callback_query: CallbackQuery, state: FSMContext):
        await state.set_state(AppointmentCreationStates.appointment_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            DATETIME_INPUT_PROMPT,
            reply_markup=back_to_records_kb(),
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

        notification_text = "Запись успешно создана!\n\n" + build_appointment_card(appointment)
        if notification_service:
            use_invite_kb = appointment.status == AppointmentStatus.PENDING
            message_id = await notification_service.notify_client_appointment_with_buttons(
                appointment, use_invite_kb=use_invite_kb
            )
            if message_id:
                await appt_mng.update_notification_message_id(appointment.id, message_id)
                notification_text += "\n✅ Уведомление отправлено клиенту"
            else:
                notification_text += "\n⚠️ Не удалось отправить уведомление клиенту (нет Telegram ID)"

        if scheduler and appointment.status == AppointmentStatus.CONFIRMED:
            await scheduler.schedule_appointment_reminders(appointment)
            notification_text += "\n⏰ Напоминания запланированы (24ч и 2ч перед приемом)"

            await scheduler.schedule_appointment_completion(appointment)
            notification_text += "\n✅ Автозавершение: через 2ч после приема"

            await scheduler.schedule_appointment_autocomplete(appointment)

        if scheduler:
            await scheduler.schedule_pending_expiry(appointment)

        await callback_query.message.edit_text(
            notification_text,
            reply_markup=back_to_records_kb(),
        )
        await appt_mng.update_admin_notification_message_id(appointment.id, callback_query.message.message_id)
        await state.clear()

    return router
