import logging
from datetime import date

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.exceptions import BotException
from bot.handlers.utils.client_utils.booking_helpers import (
    build_booking_confirmation_text,
    find_first_available_week_offset,
    generate_working_days,
)
from bot.keyboards.client.booking_cb import (
    ClientBookDayCB,
    ClientBookDayPageCB,
    ClientBookDoctorCB,
    ClientBookSlotCB,
)
from bot.keyboards.client.appointment_manage_kb import appointment_manage_empty_kb
from bot.keyboards.client.booking_kb import (
    booking_cancel_kb,
    booking_confirm_kb,
    booking_day_kb,
    booking_doctor_kb,
    booking_slot_kb,
)
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import AppointmentNotificationService
from bot.services.appointment.appointment_scheduler import AppointmentScheduler
from bot.services.utils.date_parser import get_current_tashkent_datetime
from bot.states.client.booking_states import ClientBookingStates
from bot.utils.role import RoleFilter
from bot.validators.validators import validate_purpose

logger = logging.getLogger(__name__)


def create_client_booking_router(
    appointment_repo: AppointmentRepository,
    appointment_management_service: AppointmentManagement,
    notification_service: AppointmentNotificationService,
    appointment_scheduler: AppointmentScheduler,
) -> Router:
    router = Router()

    router.message.filter(RoleFilter("client"))
    router.callback_query.filter(RoleFilter("client"))

    async def start_booking(callback_query: CallbackQuery, state: FSMContext) -> None:
        await state.clear()

        try:
            await appointment_management_service.ensure_pending_limit_not_exceeded(callback_query.from_user.id)
            staff_list = await appointment_management_service.list_bookable_staff(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        if not staff_list:
            await callback_query.message.edit_text(
                "В вашей клинике сейчас нет доступных врачей для записи.",
                reply_markup=booking_cancel_kb(),
            )
            await callback_query.answer()
            return

        if len(staff_list) == 1:
            staff = staff_list[0]
            await state.update_data(staff_user_id=staff.ID, staff_name=staff.full_name)
            await render_day_selection_start(callback_query, state)
            return

        await state.update_data(staff_options={str(staff.ID): staff.full_name for staff in staff_list})
        await state.set_state(ClientBookingStates.choose_doctor)
        await callback_query.message.edit_text(
            "Выберите специалиста:",
            reply_markup=booking_doctor_kb(staff_list),
        )
        await callback_query.answer()

    async def render_day_selection_start(callback_query: CallbackQuery, state: FSMContext) -> None:
        reference = get_current_tashkent_datetime().date()
        start_offset = find_first_available_week_offset(reference)
        await state.update_data(min_week_offset=start_offset)
        await render_day_selection(callback_query, state, start_offset)

    async def render_day_selection(callback_query: CallbackQuery, state: FSMContext, week_offset: int) -> None:
        reference = get_current_tashkent_datetime().date()
        days = generate_working_days(reference, week_offset)

        data = await state.get_data()
        min_week_offset = data.get("min_week_offset", week_offset)
        can_go_back = week_offset > min_week_offset
        can_go_forward = bool(generate_working_days(reference, week_offset + 1))

        await state.update_data(week_offset=week_offset)
        await state.set_state(ClientBookingStates.choose_day)

        await callback_query.message.edit_text(
            "Выберите день записи:",
            reply_markup=booking_day_kb(days, week_offset, can_go_back, can_go_forward),
        )
        await callback_query.answer()

    @router.callback_query(F.data == "client_book_appointment")
    async def book_appointment(callback_query: CallbackQuery, state: FSMContext) -> None:
        await start_booking(callback_query, state)

    @router.callback_query(F.data == "client_book_restart")
    async def restart_booking(callback_query: CallbackQuery, state: FSMContext) -> None:
        await start_booking(callback_query, state)

    @router.callback_query(ClientBookDoctorCB.filter())
    async def pick_doctor(callback_query: CallbackQuery, callback_data: ClientBookDoctorCB, state: FSMContext) -> None:
        data = await state.get_data()
        staff_options = data.get("staff_options", {})
        staff_name = staff_options.get(str(callback_data.staff_user_id), "Специалист")

        await state.update_data(staff_user_id=callback_data.staff_user_id, staff_name=staff_name)
        await render_day_selection_start(callback_query, state)

    @router.callback_query(ClientBookDayPageCB.filter())
    async def paginate_days(callback_query: CallbackQuery, callback_data: ClientBookDayPageCB, state: FSMContext) -> None:
        await render_day_selection(callback_query, state, callback_data.week_offset)

    @router.callback_query(ClientBookDayCB.filter())
    async def pick_day(callback_query: CallbackQuery, callback_data: ClientBookDayCB, state: FSMContext) -> None:
        day = date.fromisoformat(callback_data.day_iso)
        now = get_current_tashkent_datetime()
        data = await state.get_data()
        slots = await appointment_management_service.get_available_slots(data["staff_user_id"], day, now)

        if not slots:
            await callback_query.answer("На этот день больше нет доступных слотов.", show_alert=True)
            return

        await state.update_data(day_iso=callback_data.day_iso)
        await state.set_state(ClientBookingStates.choose_slot)

        await callback_query.message.edit_text(
            f"Выберите время на {day.strftime('%d.%m.%Y')}:",
            reply_markup=booking_slot_kb(slots),
        )
        await callback_query.answer()

    @router.callback_query(ClientBookSlotCB.filter())
    async def pick_slot(callback_query: CallbackQuery, callback_data: ClientBookSlotCB, state: FSMContext) -> None:
        data = await state.get_data()
        appointment_datetime = f"{data['day_iso']} {callback_data.slot}"

        await state.update_data(slot=callback_data.slot, appointment_datetime=appointment_datetime)
        await state.set_state(ClientBookingStates.complaint)

        await callback_query.message.edit_text(
            "Опишите жалобу или причину визита (от 2 до 100 символов):",
            reply_markup=booking_cancel_kb(),
        )
        await callback_query.answer()

    @router.message(ClientBookingStates.complaint, F.text)
    async def process_complaint(message: Message, state: FSMContext, current_user: User) -> None:
        try:
            complaint = validate_purpose(message.text)
        except BotException as e:
            await message.answer(str(e))
            return

        await state.update_data(complaint=complaint)
        await state.set_state(ClientBookingStates.confirm)

        data = await state.get_data()
        day = date.fromisoformat(data["day_iso"])

        text = build_booking_confirmation_text(
            doctor_name=data["staff_name"],
            day=day,
            slot=data["slot"],
            complaint=complaint,
            clinic_name=current_user.clinic_name,
        )

        await message.answer(text, reply_markup=booking_confirm_kb())

    @router.callback_query(ClientBookingStates.confirm, F.data == "client_book_submit")
    async def submit_booking(callback_query: CallbackQuery, state: FSMContext, current_user: User) -> None:
        data = await state.get_data()

        try:
            appointment = await appointment_management_service.create_self_booking(
                callback_query.from_user.id,
                {
                    "staff_user_id": data["staff_user_id"],
                    "appointment_datetime": data["appointment_datetime"],
                    "complaint": data["complaint"],
                },
            )
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        await state.clear()

        await callback_query.message.edit_text(
            "✅ Заявка отправлена. Ожидайте подтверждения от клиники.",
            reply_markup=appointment_manage_empty_kb(),
        )
        await callback_query.answer()

        if notification_service and appointment.created_by_telegram_id:
            try:
                admin_message_id = await notification_service.notify_staff_new_booking_request(
                    appointment.created_by_telegram_id,
                    appointment,
                    current_user.full_name,
                )
                if admin_message_id is not None:
                    await appointment_management_service.update_admin_notification_message_id(
                        appointment.id, admin_message_id
                    )
            except Exception:
                pass  # Graceful fail если не получилось отправить

        if appointment_scheduler:
            await appointment_scheduler.schedule_pending_expiry(appointment)

    return router
