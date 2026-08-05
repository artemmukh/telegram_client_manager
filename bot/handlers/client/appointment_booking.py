import logging
from datetime import date, datetime

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import bot.messages.booking as msg
from bot.exceptions.exceptions import BotException
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
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import AppointmentNotificationService
from bot.services.appointment.appointment_scheduler import AppointmentScheduler
from bot.services.utils.date_parser import get_current_tashkent_datetime
from bot.states.client.booking_states import ClientBookingStates
from bot.utils.role import RoleFilter
from bot.validators.validators import validate_purpose

logger = logging.getLogger(__name__)


def create_client_booking_router(
    appointment_management_service: AppointmentManagement,
    notification_service: AppointmentNotificationService,
    appointment_scheduler: AppointmentScheduler,
) -> Router:
    router = Router()

    router.message.filter(RoleFilter("client"))
    router.callback_query.filter(RoleFilter("client"))

    async def start_booking(callback_query: CallbackQuery, state: FSMContext, lang: str = "ru") -> None:
        await state.clear()
        await state.update_data(language=lang)

        try:
            await appointment_management_service.ensure_pending_limit_not_exceeded(callback_query.from_user.id)
            staff_list = await appointment_management_service.list_bookable_staff(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
            return

        if not staff_list:
            await callback_query.message.edit_text(
                msg.no_available_staff(lang),
                reply_markup=booking_cancel_kb(lang=lang),
            )
            await callback_query.answer()
            return

        if len(staff_list) == 1:
            staff = staff_list[0]
            await state.update_data(staff_user_id=staff.ID, staff_name=staff.full_name)
            await render_day_selection_start(callback_query, state, lang)
            return

        await state.update_data(staff_options={str(staff.ID): staff.full_name for staff in staff_list})
        await state.set_state(ClientBookingStates.choose_doctor)
        await callback_query.message.edit_text(
            msg.choose_specialist(lang),
            reply_markup=booking_doctor_kb(staff_list, lang=lang),
        )
        await callback_query.answer()

    async def render_day_selection_start(callback_query: CallbackQuery, state: FSMContext, lang: str = "ru") -> None:
        reference = get_current_tashkent_datetime().date()
        start_offset = await appointment_management_service.find_first_available_week_offset(reference)
        await state.update_data(min_week_offset=start_offset)
        await render_day_selection(callback_query, state, start_offset, lang)

    async def render_day_selection(
        callback_query: CallbackQuery, state: FSMContext, week_offset: int, lang: str = "ru"
    ) -> None:
        reference = get_current_tashkent_datetime().date()
        days = await appointment_management_service.get_working_days(reference, week_offset)

        data = await state.get_data()
        min_week_offset = data.get("min_week_offset", week_offset)
        can_go_back = week_offset > min_week_offset
        can_go_forward = bool(await appointment_management_service.get_working_days(reference, week_offset + 1))

        await state.update_data(week_offset=week_offset)
        await state.set_state(ClientBookingStates.choose_day)

        await callback_query.message.edit_text(
            msg.choose_day(lang),
            reply_markup=booking_day_kb(days, week_offset, can_go_back, can_go_forward, lang=lang),
        )
        await callback_query.answer()

    @router.callback_query(F.data == "client_book_appointment")
    async def book_appointment(callback_query: CallbackQuery, state: FSMContext, current_user: User) -> None:
        await start_booking(callback_query, state, current_user.language)

    @router.callback_query(F.data == "client_book_restart")
    async def restart_booking(callback_query: CallbackQuery, state: FSMContext, current_user: User) -> None:
        await start_booking(callback_query, state, current_user.language)

    @router.callback_query(ClientBookDoctorCB.filter())
    async def pick_doctor(
        callback_query: CallbackQuery, callback_data: ClientBookDoctorCB, state: FSMContext, current_user: User,
    ) -> None:
        data = await state.get_data()
        staff_options = data.get("staff_options", {})
        staff_name = staff_options.get(
            str(callback_data.staff_user_id), msg.default_staff_name_fallback(current_user.language)
        )

        await state.update_data(staff_user_id=callback_data.staff_user_id, staff_name=staff_name)
        await render_day_selection_start(callback_query, state, current_user.language)

    @router.callback_query(ClientBookDayPageCB.filter())
    async def paginate_days(
        callback_query: CallbackQuery, callback_data: ClientBookDayPageCB, state: FSMContext, current_user: User,
    ) -> None:
        await render_day_selection(callback_query, state, callback_data.week_offset, current_user.language)

    @router.callback_query(ClientBookDayCB.filter())
    async def pick_day(
        callback_query: CallbackQuery, callback_data: ClientBookDayCB, state: FSMContext, current_user: User,
    ) -> None:
        lang = current_user.language
        try:
            day = date.fromisoformat(callback_data.day_iso)
        except ValueError:
            await callback_query.answer(msg.invalid_date(lang), show_alert=True)
            return

        now = get_current_tashkent_datetime()
        data = await state.get_data()
        slots = await appointment_management_service.get_available_slots(data["staff_user_id"], day, now)

        if not slots:
            reason = await appointment_management_service.get_day_block_reason(data["staff_user_id"], day, now)
            if reason is not None:
                await callback_query.answer(msg.day_blocked(reason, lang), show_alert=True)
                return

            await callback_query.answer(msg.no_slots_for_day(lang), show_alert=True)
            return

        await state.update_data(day_iso=callback_data.day_iso)
        await state.set_state(ClientBookingStates.choose_slot)

        await callback_query.message.edit_text(
            msg.choose_time_prompt(day, lang),
            reply_markup=booking_slot_kb(slots, cancel_callback_data="client_book_back_to_day", lang=lang),
        )
        await callback_query.answer()

    @router.callback_query(F.data == "client_book_back_to_day")
    async def back_to_day_selection(callback_query: CallbackQuery, state: FSMContext, current_user: User) -> None:
        data = await state.get_data()
        week_offset = data.get("week_offset", 0)
        await render_day_selection(callback_query, state, week_offset, current_user.language)

    @router.callback_query(ClientBookSlotCB.filter())
    async def pick_slot(
        callback_query: CallbackQuery, callback_data: ClientBookSlotCB, state: FSMContext, current_user: User,
    ) -> None:
        lang = current_user.language
        try:
            datetime.strptime(callback_data.slot, "%H:%M")
        except ValueError:
            await callback_query.answer(msg.invalid_time(lang), show_alert=True)
            return

        data = await state.get_data()
        appointment_datetime = f"{data['day_iso']} {callback_data.slot}"

        await state.update_data(slot=callback_data.slot, appointment_datetime=appointment_datetime)
        await state.set_state(ClientBookingStates.complaint)

        await callback_query.message.edit_text(
            msg.complaint_prompt(lang),
            reply_markup=booking_cancel_kb(cancel_callback_data="client_book_back_to_day", lang=lang),
        )
        await callback_query.answer()

    @router.message(ClientBookingStates.complaint, F.text)
    async def process_complaint(message: Message, state: FSMContext, current_user: User) -> None:
        try:
            complaint = validate_purpose(message.text)
        except BotException as e:
            await message.answer(e.localized(current_user.language))
            return

        await state.update_data(complaint=complaint)
        await state.set_state(ClientBookingStates.confirm)

        data = await state.get_data()
        day = date.fromisoformat(data["day_iso"])

        text = msg.build_booking_confirmation_text(
            doctor_name=data["staff_name"],
            day=day,
            slot=data["slot"],
            complaint=complaint,
            clinic_name=current_user.clinic_name,
            lang=current_user.language,
        )

        await message.answer(text, reply_markup=booking_confirm_kb(lang=current_user.language))

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
            await callback_query.answer(e.localized(current_user.language), show_alert=True)
            return

        await state.clear()

        await callback_query.message.edit_text(
            msg.submitted(current_user.language),
            reply_markup=appointment_manage_empty_kb(current_user.language),
        )
        await callback_query.answer()

        if notification_service:
            try:
                recipients = await appointment_management_service.resolve_notification_recipients(appointment)
            except Exception:
                logger.exception(f"Failed to resolve notification recipients for appointment {appointment.id}")
                recipients = []
            for recipient in recipients:
                try:
                    admin_message_id = await notification_service.notify_staff_new_booking_request(
                        recipient.telegram_user_id,
                        appointment,
                        current_user.full_name,
                    )
                    # admin_notification_message_id is a single column and can only reply-thread
                    # to one recipient's chat; keep the first successful send (the treating
                    # doctor, matching prior single-recipient behavior).
                    if admin_message_id is not None and appointment.admin_notification_message_id is None:
                        await appointment_management_service.update_admin_notification_message_id(
                            appointment.id, admin_message_id
                        )
                        appointment.admin_notification_message_id = admin_message_id

                    if admin_message_id is not None:
                        await appointment_management_service.record_notification(
                            appointment.id, recipient.telegram_user_id, admin_message_id, kind="booking",
                        )
                except Exception:
                    logger.exception(
                        f"Failed to send booking notification to {recipient.telegram_user_id} "
                        f"for appointment {appointment.id}"
                    )

        if appointment_scheduler:
            await appointment_scheduler.schedule_pending_expiry(appointment)

    return router
