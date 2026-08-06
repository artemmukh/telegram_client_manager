import logging
from datetime import date, datetime

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

import bot.messages.booking as msg
from bot.exceptions.exceptions import BotException
from bot.handlers.utils.appointment_slot_helpers import answer_no_slots_for_day
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

_NEW_DAY_PROMPT = {
    "ru": "Выберите новый день записи:",
    "uz": "Yangi qabul kunini tanlang:",
}

_APPOINTMENT_NOT_FOUND_DOT = {
    "ru": "Запись не найдена.",
    "uz": "Yozuv topilmadi.",
}

_RESCHEDULE_CONFIRM_PROMPT_TEMPLATE = {
    "ru": "Проверьте новое время записи:\n\n📅 Новое время: {display}\n\nОтправить заявку на перенос?",
    "uz": "Yozuvning yangi vaqtini tekshiring:\n\n📅 Yangi vaqt: {display}\n\nKo'chirish arizasini yuborishni xohlaysizmi?",
}

_DIRECT_EDIT_SUCCESS = {
    "ru": "✅ Время заявки изменено.",
    "uz": "✅ Ariza vaqti o'zgartirildi.",
}

_UNKNOWN_CLIENT_LABEL = {
    "ru": "Неизвестный клиент",
    "uz": "Noma'lum mijoz",
}

_RESCHEDULE_REQUEST_SENT_TEMPLATE = {
    "ru": (
        "✅ Заявка на перенос отправлена. Ожидайте решения клиники.\n\n"
        "Текущее время: {old}\n"
        "Предложенное время: {new}"
    ),
    "uz": (
        "✅ Ko'chirish arizasi yuborildi. Klinika qarorini kuting.\n\n"
        "Hozirgi vaqt: {old}\n"
        "Taklif qilingan vaqt: {new}"
    ),
}


def create_client_reschedule_router(
    appointment_management_service: AppointmentManagement,
    notification_service: AppointmentNotificationService,
    appointment_scheduler: AppointmentScheduler,
) -> Router:
    router = Router()

    router.message.filter(RoleFilter("client"))
    router.callback_query.filter(RoleFilter("client"))

    async def render_day_selection(
        callback_query: CallbackQuery, state: FSMContext, appointment_id: int, week_offset: int, lang: str = "ru",
    ) -> None:
        reference = get_current_tashkent_datetime().date()
        days = await appointment_management_service.get_working_days(reference, week_offset)

        data = await state.get_data()
        min_week_offset = data.get("min_week_offset", week_offset)
        can_go_back = week_offset > min_week_offset
        can_go_forward = bool(await appointment_management_service.get_working_days(reference, week_offset + 1))

        await state.update_data(week_offset=week_offset)
        await state.set_state(ClientRescheduleStates.choose_day)

        await callback_query.message.edit_text(
            _NEW_DAY_PROMPT.get(lang, _NEW_DAY_PROMPT["ru"]),
            reply_markup=reschedule_day_kb(appointment_id, days, week_offset, can_go_back, can_go_forward, lang),
        )
        await callback_query.answer()

    async def render_manage_card(callback_query: CallbackQuery, appointment_id: int, lang: str = "ru") -> None:
        appointment = await appointment_management_service.get_appointment_for_client(
            appointment_id, callback_query.from_user.id,
        )
        if appointment is None:
            await callback_query.answer(_APPOINTMENT_NOT_FOUND_DOT.get(lang, _APPOINTMENT_NOT_FOUND_DOT["ru"]), show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_history_card_text(appointment, lang),
            reply_markup=appointment_manage_card_kb(appointment, page=1, lang=lang),
        )

    async def render_history_card(
        callback_query: CallbackQuery, appointment_id: int, tab: str, page: int, lang: str = "ru",
    ) -> None:
        appointment = await appointment_management_service.get_appointment_for_client(
            appointment_id, callback_query.from_user.id,
        )
        if appointment is None:
            await callback_query.answer(_APPOINTMENT_NOT_FOUND_DOT.get(lang, _APPOINTMENT_NOT_FOUND_DOT["ru"]), show_alert=True)
            return

        now = get_current_tashkent_datetime()
        can_cancel = appointment.status == AppointmentStatus.CONFIRMED and is_appointment_upcoming(appointment, now)
        can_reschedule = can_cancel and appointment.proposed_datetime is None

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_history_card_text(appointment, lang),
            reply_markup=appointment_history_card_kb(appointment, tab, page, can_cancel, can_reschedule, lang),
        )

    @router.callback_query(ClientRescheduleStartCB.filter())
    async def start_reschedule(
        callback_query: CallbackQuery, callback_data: ClientRescheduleStartCB, state: FSMContext, current_user: User,
    ) -> None:
        lang = current_user.language
        appointment_id = callback_data.appointment_id

        appointment = await appointment_management_service.get_appointment_for_client(
            appointment_id, callback_query.from_user.id,
        )
        if appointment is None:
            await callback_query.answer(_APPOINTMENT_NOT_FOUND_DOT.get(lang, _APPOINTMENT_NOT_FOUND_DOT["ru"]), show_alert=True)
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
        start_offset = await appointment_management_service.find_first_available_week_offset(reference)
        await state.update_data(min_week_offset=start_offset)
        await render_day_selection(callback_query, state, appointment_id, start_offset, lang)

    @router.callback_query(ClientRescheduleDayPageCB.filter())
    async def paginate_days(
        callback_query: CallbackQuery, callback_data: ClientRescheduleDayPageCB, state: FSMContext, current_user: User,
    ) -> None:
        await render_day_selection(
            callback_query, state, callback_data.appointment_id, callback_data.week_offset, current_user.language,
        )

    @router.callback_query(ClientRescheduleDayCB.filter())
    async def pick_day(
        callback_query: CallbackQuery, callback_data: ClientRescheduleDayCB, state: FSMContext, current_user: User,
    ) -> None:
        lang = current_user.language
        try:
            day = date.fromisoformat(callback_data.day_iso)
        except ValueError:
            await callback_query.answer(msg.invalid_date(lang), show_alert=True)
            return

        now = get_current_tashkent_datetime()
        data = await state.get_data()
        slots = await appointment_management_service.get_available_slots(
            data["doctor_id"], day, now, exclude_appointment_id=data["appointment_id"]
        )

        if not slots:
            await answer_no_slots_for_day(
                appointment_management_service, callback_query, data["doctor_id"], day, now,
                msg.no_slots_for_day(lang), lang,
            )
            return

        await state.update_data(day_iso=callback_data.day_iso)
        await state.set_state(ClientRescheduleStates.choose_slot)

        await callback_query.message.edit_text(
            msg.choose_time_prompt(day, lang),
            reply_markup=reschedule_slot_kb(callback_data.appointment_id, slots, lang),
        )
        await callback_query.answer()

    @router.callback_query(ClientRescheduleSlotCB.filter())
    async def pick_slot(
        callback_query: CallbackQuery, callback_data: ClientRescheduleSlotCB, state: FSMContext, current_user: User,
    ) -> None:
        lang = current_user.language
        data = await state.get_data()
        new_datetime = f"{data['day_iso']} {callback_data.slot}"

        try:
            parsed_datetime = datetime.fromisoformat(new_datetime)
        except ValueError:
            await callback_query.answer(msg.invalid_time(lang), show_alert=True)
            return

        await state.update_data(slot=callback_data.slot, new_datetime=new_datetime)
        await state.set_state(ClientRescheduleStates.confirm)

        display_datetime = format_datetime_for_display(parsed_datetime, lang)
        template = _RESCHEDULE_CONFIRM_PROMPT_TEMPLATE.get(lang, _RESCHEDULE_CONFIRM_PROMPT_TEMPLATE["ru"])
        text = template.format(display=display_datetime)

        await callback_query.message.edit_text(
            text, reply_markup=reschedule_confirm_kb(callback_data.appointment_id, lang),
        )
        await callback_query.answer()

    @router.callback_query(ClientRescheduleStates.confirm, ClientRescheduleSubmitCB.filter())
    async def submit_reschedule(
        callback_query: CallbackQuery, callback_data: ClientRescheduleSubmitCB, state: FSMContext, current_user: User,
    ) -> None:
        lang = current_user.language
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
            await callback_query.answer(e.localized(lang), show_alert=True)
            return

        await state.clear()

        is_direct_edit = appointment.proposed_datetime is None

        if origin == "history" and tab:
            success_kb = appointment_history_card_kb(
                appointment, tab, page, can_cancel=False, can_reschedule=False, lang=lang,
            )
        else:
            success_kb = appointment_manage_empty_kb(lang)

        if is_direct_edit:
            message_text = _DIRECT_EDIT_SUCCESS.get(lang, _DIRECT_EDIT_SUCCESS["ru"])
        else:
            old_display = format_datetime_for_display(datetime.fromisoformat(appointment.datetime), lang)
            new_display = format_datetime_for_display(datetime.fromisoformat(appointment.proposed_datetime), lang)
            template = _RESCHEDULE_REQUEST_SENT_TEMPLATE.get(lang, _RESCHEDULE_REQUEST_SENT_TEMPLATE["ru"])
            message_text = template.format(old=old_display, new=new_display)
        await callback_query.message.edit_text(message_text, reply_markup=success_kb)
        await callback_query.answer()

        if notification_service:
            try:
                recipients = await appointment_management_service.resolve_notification_recipients(appointment)
            except Exception:
                recipients = []
            for recipient in recipients:
                try:
                    if is_direct_edit:
                        await notification_service.notify_admin_client_changed_time(
                            recipient.telegram_user_id,
                            appointment,
                            current_user.full_name if current_user else _UNKNOWN_CLIENT_LABEL.get(lang, _UNKNOWN_CLIENT_LABEL["ru"]),
                        )
                    else:
                        message_id = await notification_service.notify_staff_reschedule_requested(
                            recipient.telegram_user_id,
                            appointment,
                            current_user.full_name if current_user else _UNKNOWN_CLIENT_LABEL.get(lang, _UNKNOWN_CLIENT_LABEL["ru"]),
                        )
                        if message_id is not None:
                            await appointment_management_service.record_notification(
                                appointment.id, recipient.telegram_user_id, message_id, kind="reschedule",
                            )
                except Exception:
                    pass  # Graceful fail если не получилось отправить

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

    @router.callback_query(ClientRescheduleCancelCB.filter())
    async def cancel_reschedule(
        callback_query: CallbackQuery, callback_data: ClientRescheduleCancelCB, state: FSMContext, current_user: User,
    ) -> None:
        lang = current_user.language
        data = await state.get_data()
        origin = data.get("origin", "manage")
        tab = data.get("tab")
        page = data.get("page", 1)

        await state.clear()
        await state.update_data(origin=origin, tab=tab, page=page)

        if origin == "history" and tab:
            await render_history_card(callback_query, callback_data.appointment_id, tab, page, lang)
        else:
            await render_manage_card(callback_query, callback_data.appointment_id, lang)

    return router
