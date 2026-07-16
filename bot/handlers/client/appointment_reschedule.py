import logging
from datetime import date, datetime

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.exceptions.exceptions import BotException
from bot.handlers.utils.client_utils.booking_helpers import (
    find_first_available_week_offset,
    generate_working_days,
)
from bot.handlers.utils.client_utils.appointment_history_helpers import build_history_card_text
from bot.keyboards.client.appointment_history_kb import appointment_history_card_kb
from bot.keyboards.client.appointment_manage_kb import appointment_manage_card_kb, appointment_manage_empty_kb
from bot.keyboards.client.reschedule_cb import (
    ClientRescheduleCancelCB,
    ClientRescheduleDayCB,
    ClientRescheduleDayPageCB,
    ClientRescheduleSlotCB,
    ClientRescheduleStartCB,
    ClientRescheduleSubmitCB,
)
from bot.keyboards.client.reschedule_kb import (
    reschedule_confirm_kb,
    reschedule_day_kb,
    reschedule_slot_kb,
)
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import AppointmentNotificationService
from bot.services.appointment.appointment_scheduler import AppointmentScheduler
from bot.services.utils.date_parser import (
    format_datetime_for_display,
    get_current_tashkent_datetime,
    is_appointment_upcoming,
)
from bot.states.client.reschedule_states import ClientRescheduleStates
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.role import RoleFilter

logger = logging.getLogger(__name__)


def create_client_reschedule_router(
    appointment_repo: AppointmentRepository,
    appointment_management_service: AppointmentManagement,
    notification_service: AppointmentNotificationService,
    appointment_scheduler: AppointmentScheduler,
) -> Router:
    router = Router()

    router.message.filter(RoleFilter("client"))
    router.callback_query.filter(RoleFilter("client"))

    async def render_day_selection(
        callback_query: CallbackQuery, state: FSMContext, appointment_id: int, week_offset: int,
    ) -> None:
        reference = get_current_tashkent_datetime().date()
        days = generate_working_days(reference, week_offset)

        data = await state.get_data()
        min_week_offset = data.get("min_week_offset", week_offset)
        can_go_back = week_offset > min_week_offset
        can_go_forward = bool(generate_working_days(reference, week_offset + 1))

        await state.update_data(week_offset=week_offset)
        await state.set_state(ClientRescheduleStates.choose_day)

        await callback_query.message.edit_text(
            "Выберите новый день записи:",
            reply_markup=reschedule_day_kb(appointment_id, days, week_offset, can_go_back, can_go_forward),
        )
        await callback_query.answer()

    async def render_manage_card(callback_query: CallbackQuery, appointment_id: int) -> None:
        appointment = await appointment_management_service.get_appointment_for_client(
            appointment_id, callback_query.from_user.id,
        )
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_history_card_text(appointment),
            reply_markup=appointment_manage_card_kb(appointment, page=1),
        )

    async def render_history_card(
        callback_query: CallbackQuery, appointment_id: int, tab: str, page: int,
    ) -> None:
        appointment = await appointment_management_service.get_appointment_for_client(
            appointment_id, callback_query.from_user.id,
        )
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        now = get_current_tashkent_datetime()
        can_cancel = appointment.status == AppointmentStatus.CONFIRMED and is_appointment_upcoming(appointment, now)
        can_reschedule = can_cancel and appointment.proposed_datetime is None

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_history_card_text(appointment),
            reply_markup=appointment_history_card_kb(appointment, tab, page, can_cancel, can_reschedule),
        )

    @router.callback_query(ClientRescheduleStartCB.filter())
    async def start_reschedule(
        callback_query: CallbackQuery, callback_data: ClientRescheduleStartCB, state: FSMContext,
    ) -> None:
        appointment_id = callback_data.appointment_id

        appointment = await appointment_management_service.get_appointment_for_client(
            appointment_id, callback_query.from_user.id,
        )
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        origin_data = await state.get_data()
        origin = origin_data.get("origin", "manage")
        origin_tab = origin_data.get("tab")
        origin_page = origin_data.get("page", 1)

        await state.clear()
        await state.update_data(
            appointment_id=appointment_id, origin=origin, tab=origin_tab, page=origin_page,
            doctor_id=appointment.doctor_id,
        )

        reference = get_current_tashkent_datetime().date()
        start_offset = find_first_available_week_offset(reference)
        await state.update_data(min_week_offset=start_offset)
        await render_day_selection(callback_query, state, appointment_id, start_offset)

    @router.callback_query(ClientRescheduleDayPageCB.filter())
    async def paginate_days(
        callback_query: CallbackQuery, callback_data: ClientRescheduleDayPageCB, state: FSMContext,
    ) -> None:
        await render_day_selection(
            callback_query, state, callback_data.appointment_id, callback_data.week_offset,
        )

    @router.callback_query(ClientRescheduleDayCB.filter())
    async def pick_day(
        callback_query: CallbackQuery, callback_data: ClientRescheduleDayCB, state: FSMContext,
    ) -> None:
        day = date.fromisoformat(callback_data.day_iso)
        now = get_current_tashkent_datetime()
        data = await state.get_data()
        slots = await appointment_management_service.get_available_slots(data["doctor_id"], day, now)

        if not slots:
            await callback_query.answer("На этот день больше нет доступных слотов.", show_alert=True)
            return

        await state.update_data(day_iso=callback_data.day_iso)
        await state.set_state(ClientRescheduleStates.choose_slot)

        await callback_query.message.edit_text(
            f"Выберите время на {day.strftime('%d.%m.%Y')}:",
            reply_markup=reschedule_slot_kb(callback_data.appointment_id, slots),
        )
        await callback_query.answer()

    @router.callback_query(ClientRescheduleSlotCB.filter())
    async def pick_slot(
        callback_query: CallbackQuery, callback_data: ClientRescheduleSlotCB, state: FSMContext,
    ) -> None:
        data = await state.get_data()
        new_datetime = f"{data['day_iso']} {callback_data.slot}"

        await state.update_data(slot=callback_data.slot, new_datetime=new_datetime)
        await state.set_state(ClientRescheduleStates.confirm)

        display_datetime = format_datetime_for_display(datetime.fromisoformat(new_datetime))
        text = (
            "Проверьте новое время записи:\n\n"
            f"📅 Новое время: {display_datetime}\n\n"
            "Отправить заявку на перенос?"
        )

        await callback_query.message.edit_text(text, reply_markup=reschedule_confirm_kb(callback_data.appointment_id))
        await callback_query.answer()

    @router.callback_query(ClientRescheduleStates.confirm, ClientRescheduleSubmitCB.filter())
    async def submit_reschedule(
        callback_query: CallbackQuery, callback_data: ClientRescheduleSubmitCB, state: FSMContext, current_user: User,
    ) -> None:
        data = await state.get_data()
        appointment_id = callback_data.appointment_id
        origin = data.get("origin", "manage")
        tab = data.get("tab")
        page = data.get("page", 1)

        try:
            appointment = await appointment_management_service.request_reschedule_by_client(
                appointment_id, callback_query.from_user.id, data["new_datetime"],
            )
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        await state.clear()

        is_direct_edit = appointment.proposed_datetime is None

        if origin == "history" and tab:
            success_kb = appointment_history_card_kb(appointment, tab, page, can_cancel=False, can_reschedule=False)
        else:
            success_kb = appointment_manage_empty_kb()

        message_text = (
            "✅ Время заявки изменено."
            if is_direct_edit
            else "✅ Заявка на перенос отправлена. Ожидайте решения клиники."
        )
        await callback_query.message.edit_text(message_text, reply_markup=success_kb)
        await callback_query.answer()

        if notification_service and appointment.created_by_telegram_id:
            try:
                if is_direct_edit:
                    await notification_service.notify_admin_client_changed_time(
                        appointment.created_by_telegram_id,
                        appointment,
                        current_user.full_name if current_user else "Неизвестный клиент",
                    )
                else:
                    await notification_service.notify_staff_reschedule_requested(
                        appointment.created_by_telegram_id,
                        appointment,
                        current_user.full_name if current_user else "Неизвестный клиент",
                    )
            except Exception:
                pass  # Graceful fail если не получилось отправить

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

    @router.callback_query(ClientRescheduleCancelCB.filter())
    async def cancel_reschedule(
        callback_query: CallbackQuery, callback_data: ClientRescheduleCancelCB, state: FSMContext,
    ) -> None:
        data = await state.get_data()
        origin = data.get("origin", "manage")
        tab = data.get("tab")
        page = data.get("page", 1)

        await state.clear()
        await state.update_data(origin=origin, tab=tab, page=page)

        if origin == "history" and tab:
            await render_history_card(callback_query, callback_data.appointment_id, tab, page)
        else:
            await render_manage_card(callback_query, callback_data.appointment_id)

    return router
