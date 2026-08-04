import logging
from datetime import date, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config.clinic_instances import DATEPARSER_BY_INSTANCE as DATA_PARSE_MODE
from bot.exceptions.appointment_exceptions import AppointmentAlreadyDecidedError, AppointmentNotFoundError
from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import ValidationError
from bot.handlers.utils.admin_utils import appointment_helpers as ah
from bot.handlers.utils.admin_utils.appointment_browser_helpers import (
    edit_tracked_message,
    remember_tracked_message,
)
from bot.handlers.utils.admin_utils.appointment_calendar_helpers import clamp_calendar_date, clamp_month_to_range
from bot.handlers.utils.admin_utils.appointment_decision_helpers import (
    invalidate_actor_stale_message,
    invalidate_sibling_notifications,
)
from bot.handlers.utils.admin_utils.appointment_helpers import (
    build_appointment_card,
    datetime_processing,
)
from bot.keyboards.admin.record_management_kb.appointment_browser_cb import ApptCalendarDayCB, ApptCalendarMonthCB
from bot.keyboards.admin.record_management_kb.appointment_creation_cb import AdminOccupiedSlotCB
from bot.keyboards.admin.record_management_kb.booking_request_cb import BookingRequestActionCB
from bot.keyboards.admin.record_management_kb.booking_request_kb import (
    booking_request_confirm_propose_kb,
    booking_request_kb,
    booking_request_propose_cancel_kb,
)
from bot.keyboards.client.booking_cb import ClientBookSlotCB
from bot.models.user import User
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.utils.date_parser import (
    format_datetime_for_db,
    format_datetime_for_display,
    get_current_tashkent_datetime,
)
from bot.states.admin.record_management.booking_negotiation_states import BookingNegotiationStates
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.role import RoleFilter

logger = logging.getLogger(__name__)

_REQUEST_NOT_FOUND = {
    "ru": "Заявка не найдена",
    "uz": "Ariza topilmadi",
}

_REQUEST_NOT_FOUND_DOT = {
    "ru": "Заявка не найдена.",
    "uz": "Ariza topilmadi.",
}

_REQUEST_CONFIRMED = {
    "ru": "Заявка подтверждена",
    "uz": "Ariza tasdiqlandi",
}

_REQUEST_REJECTED = {
    "ru": "Заявка отклонена",
    "uz": "Ariza rad etildi",
}

_ASK_NEW_DATETIME = {
    "ru": "Введите новую дату и время (например: завтра в 15:00):",
    "uz": "Yangi sana va vaqtni kiriting (masalan: ertaga soat 15:00):",
}

_PROPOSE_DATETIME_TO_CLIENT = {
    "ru": "Предложить клиенту время: {value}?",
    "uz": "Mijozga vaqt taklif qilinsinmi: {value}?",
}

_NO_SLOTS_FOR_DAY = {
    "ru": "На этот день нет доступных слотов.",
    "uz": "Bu kunga bo'sh vaqt yo'q.",
}

_DATE_PROCESSING_ERROR = {
    "ru": "Ошибка: не удалось обработать дату. Попробуйте снова.",
    "uz": "Xatolik: sanani qayta ishlab bo'lmadi. Qaytadan urinib ko'ring.",
}

_GENERIC_ERROR = {
    "ru": "Ошибка: {error}",
    "uz": "Xatolik: {error}",
}

_TIME_CHANGED = {
    "ru": "Время записи изменено",
    "uz": "Yozuv vaqti o'zgartirildi",
}

_TIME_CHANGED_TO = {
    "ru": "✅ Время записи изменено: {value}",
    "uz": "✅ Yozuv vaqti o'zgartirildi: {value}",
}

_TIME_CHANGED_AND_NOTIFIED = {
    "ru": "Время записи изменено, клиенту отправлено уведомление",
    "uz": "Yozuv vaqti o'zgartirildi, mijozga xabar yuborildi",
}

_NEW_TIME_ASSIGNED = {
    "ru": "🔁 Клиенту назначено новое время: {value}\nОжидаем подтверждения клиента.",
    "uz": "🔁 Mijozga yangi vaqt tayinlandi: {value}\nMijoz tasdiqlashini kutmoqdamiz.",
}

_UNKNOWN_CLIENT_LABEL = {
    "ru": "Клиент",
    "uz": "Mijoz",
}


def _format_datetime_value(value: str, lang: str = "ru") -> str:
    try:
        return format_datetime_for_display(datetime.fromisoformat(value), lang)
    except ValueError:
        return value


def create_admin_booking_requests_router(
    instance: str,
    appointment_repo, user_repo, staff_repo, clinic_repo, notification_service=None, appointment_scheduler=None,
) -> Router:
    router = Router()

    appt_mng = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    async def invalidate_booking_siblings(callback_query: CallbackQuery, appointment) -> None:
        if not notification_service:
            return
        try:
            actor = await appt_mng.get_user_by_telegram_id(callback_query.from_user.id)
            decided_by_label = await appt_mng.resolve_decision_label(actor.ID if actor else None)
            outcome_text = appt_mng.resolve_decision_outcome_text(appointment, "booking")
            await invalidate_sibling_notifications(
                notification_service, appt_mng, appointment.id, "booking",
                callback_query.from_user.id, decided_by_label, outcome_text,
            )
        except Exception as e:
            logger.warning(
                f"Failed to invalidate sibling booking notifications for appointment {appointment.id}: {e}"
            )

    async def invalidate_own_stale_booking_message(
        callback_query: CallbackQuery, error: AppointmentAlreadyDecidedError, lang: str,
    ) -> None:
        if not notification_service:
            return
        try:
            await invalidate_actor_stale_message(
                notification_service, error,
                callback_query.message.chat.id, callback_query.message.message_id, lang,
            )
        except Exception as e:
            logger.warning(
                f"Failed to invalidate own stale booking message: {e}"
            )

    async def notify_staff_booking_decision(
        callback_query: CallbackQuery, appointment, confirmed: bool, lang: str,
    ) -> None:
        if not notification_service:
            return
        try:
            actor = await appt_mng.get_user_by_telegram_id(callback_query.from_user.id)
            actor_label = await appt_mng.resolve_decision_label(actor.ID if actor else None)
            client = await appt_mng.get_client_by_id(appointment.client_id)
            client_name = client.full_name if client else _UNKNOWN_CLIENT_LABEL.get(lang, _UNKNOWN_CLIENT_LABEL["ru"])
            recipients = await appt_mng.resolve_notification_recipients(appointment)
        except Exception as e:
            logger.warning(
                f"Failed to resolve staff recipients for booking decision on appointment {appointment.id}: {e}"
            )
            return

        for recipient in recipients:
            if recipient.telegram_user_id == callback_query.from_user.id:
                continue
            try:
                if confirmed:
                    await notification_service.notify_staff_booking_confirmed(
                        recipient.telegram_user_id, appointment, actor_label, client_name,
                    )
                else:
                    await notification_service.notify_staff_booking_rejected(
                        recipient.telegram_user_id, appointment, actor_label, client_name,
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to notify staff {recipient.telegram_user_id} about booking decision "
                    f"for appointment {appointment.id}: {e}"
                )

    @router.callback_query(BookingRequestActionCB.filter(F.action == "confirm"))
    async def confirm_request(callback_query: CallbackQuery, callback_data: BookingRequestActionCB, current_user: User):
        lang = current_user.language
        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer(_REQUEST_NOT_FOUND.get(lang, _REQUEST_NOT_FOUND["ru"]), show_alert=True)
            return

        try:
            appointment = await appt_mng.confirm_pending_request(
                callback_data.appointment_id, callback_query.from_user.id
            )
        except AppointmentNotFoundError:
            await callback_query.answer(_REQUEST_NOT_FOUND.get(lang, _REQUEST_NOT_FOUND["ru"]), show_alert=True)
            return
        except AppointmentAlreadyDecidedError as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
            await invalidate_own_stale_booking_message(callback_query, e, lang)
            return
        except BotException as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

        await notify_client_confirmed(appointment)

        await callback_query.answer(_REQUEST_CONFIRMED.get(lang, _REQUEST_CONFIRMED["ru"]))
        await callback_query.message.edit_text(build_appointment_card(appointment, lang))
        await invalidate_booking_siblings(callback_query, appointment)
        await notify_staff_booking_decision(callback_query, appointment, confirmed=True, lang=lang)

    @router.callback_query(BookingRequestActionCB.filter(F.action == "reject"))
    async def reject_request(callback_query: CallbackQuery, callback_data: BookingRequestActionCB, current_user: User):
        lang = current_user.language
        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer(_REQUEST_NOT_FOUND.get(lang, _REQUEST_NOT_FOUND["ru"]), show_alert=True)
            return

        try:
            appointment = await appt_mng.reject_pending_request(
                callback_data.appointment_id, callback_query.from_user.id
            )
        except AppointmentNotFoundError:
            await callback_query.answer(_REQUEST_NOT_FOUND.get(lang, _REQUEST_NOT_FOUND["ru"]), show_alert=True)
            return
        except AppointmentAlreadyDecidedError as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
            await invalidate_own_stale_booking_message(callback_query, e, lang)
            return
        except BotException as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

        if notification_service:
            try:
                await notification_service.notify_client_booking_request_rejected(appointment)
            except Exception as e:
                logger.warning(
                    f"Failed to notify client about rejection for appointment {callback_data.appointment_id}: {e}"
                )

        await callback_query.answer(_REQUEST_REJECTED.get(lang, _REQUEST_REJECTED["ru"]))
        await callback_query.message.edit_text(build_appointment_card(appointment, lang))
        await invalidate_booking_siblings(callback_query, appointment)
        await notify_staff_booking_decision(callback_query, appointment, confirmed=False, lang=lang)

    @router.callback_query(BookingRequestActionCB.filter(F.action == "propose"))
    async def start_propose_datetime(
        callback_query: CallbackQuery, callback_data: BookingRequestActionCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        await state.update_data(appointment_id=callback_data.appointment_id)

        if DATA_PARSE_MODE.get(instance) == "slots":
            appointment = await appt_mng.get_appointment_for_admin(
                callback_data.appointment_id, callback_query.from_user.id
            )
            if appointment is None:
                await callback_query.answer(_REQUEST_NOT_FOUND_DOT.get(lang, _REQUEST_NOT_FOUND_DOT["ru"]), show_alert=True)
                return

            await state.update_data(staff_user_id=appointment.doctor_id, old_datetime=appointment.datetime)
            await ah.render_propose_calendar_start(
                callback_query, state, callback_data.appointment_id,
                choose_day_state=BookingNegotiationStates.choose_day, cb_class=BookingRequestActionCB,
                today=get_current_tashkent_datetime().date(), lang=lang,
            )
            return

        await state.set_state(BookingNegotiationStates.propose_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            _ASK_NEW_DATETIME.get(lang, _ASK_NEW_DATETIME["ru"]),
            reply_markup=booking_request_propose_cancel_kb(callback_data.appointment_id, lang=lang),
        )
        await remember_tracked_message(state, callback_query.message)

    @router.message(BookingNegotiationStates.propose_datetime, F.text)
    async def process_propose_datetime(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        if not await datetime_processing(message, state, BookingNegotiationStates.confirm_propose_datetime, lang=lang):
            return

        data = await state.get_data()
        await message.delete()
        await edit_tracked_message(
            message.bot, state,
            text=_PROPOSE_DATETIME_TO_CLIENT.get(lang, _PROPOSE_DATETIME_TO_CLIENT["ru"]).format(
                value=data.get('appointment_datetime_display'),
            ),
            reply_markup=booking_request_confirm_propose_kb(data["appointment_id"], lang=lang),
        )

    # Router registration order matters here: this router is registered before
    # appointment_browser's (see bot/run.py), and browser's
    # ApptCalendarMonthCB/ApptCalendarDayCB handlers are NOT state-filtered.
    # State-filtering these two handlers to choose_day lets a propose-datetime
    # calendar session take priority while its own state is active, and falls
    # through to the browser's calendar handlers otherwise -- keep both the
    # state filter and the router registration order intact.
    @router.callback_query(BookingNegotiationStates.choose_day, ApptCalendarMonthCB.filter())
    async def change_propose_calendar_month(
        callback_query: CallbackQuery, callback_data: ApptCalendarMonthCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        year, month = clamp_month_to_range(callback_data.year, callback_data.month)
        data = await state.get_data()
        back_callback_data, back_label = ah.propose_calendar_back_target(BookingRequestActionCB, data["appointment_id"], lang)
        await ah.render_calendar_month(
            callback_query, state, year, month,
            choose_day_state=BookingNegotiationStates.choose_day,
            back_callback_data=back_callback_data, back_label=back_label, lang=lang,
        )

    @router.callback_query(BookingNegotiationStates.choose_day, ApptCalendarDayCB.filter())
    async def pick_propose_calendar_day(
        callback_query: CallbackQuery, callback_data: ApptCalendarDayCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        year, month, day_num = clamp_calendar_date(callback_data.year, callback_data.month, callback_data.day)
        day_iso = date(year, month, day_num).isoformat()
        now = get_current_tashkent_datetime()

        if not await ah.render_propose_slot_grid(
            appt_mng, callback_query, state, day_iso, choose_slot_state=BookingNegotiationStates.choose_slot, now=now,
            lang=lang,
        ):
            await callback_query.answer(_NO_SLOTS_FOR_DAY.get(lang, _NO_SLOTS_FOR_DAY["ru"]), show_alert=True)
            return

        await callback_query.answer()

    @router.callback_query(BookingNegotiationStates.choose_slot, F.data == "admin_book_back_to_day")
    async def back_to_propose_day_selection(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        data = await state.get_data()
        today = get_current_tashkent_datetime().date()
        year = data.get("calendar_year", today.year)
        month = data.get("calendar_month", today.month)
        back_callback_data, back_label = ah.propose_calendar_back_target(BookingRequestActionCB, data["appointment_id"], lang)
        await ah.render_calendar_month(
            callback_query, state, year, month,
            choose_day_state=BookingNegotiationStates.choose_day,
            back_callback_data=back_callback_data, back_label=back_label, lang=lang,
        )

    @router.callback_query(BookingNegotiationStates.choose_slot, AdminOccupiedSlotCB.filter())
    async def view_propose_occupied_slot(
        callback_query: CallbackQuery, callback_data: AdminOccupiedSlotCB, state: FSMContext, current_user: User,
    ):
        await ah.render_occupied_slot_card(appt_mng, callback_query, callback_data.appointment_id, lang=current_user.language)

    @router.callback_query(BookingNegotiationStates.choose_slot, F.data == "admin_book_back_to_slots")
    async def back_to_propose_slot_grid(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        data = await state.get_data()
        now = get_current_tashkent_datetime()
        await ah.render_propose_slot_grid(
            appt_mng, callback_query, state, data["day_iso"], choose_slot_state=BookingNegotiationStates.choose_slot,
            now=now, lang=current_user.language,
        )
        await callback_query.answer()

    @router.callback_query(BookingNegotiationStates.choose_slot, ClientBookSlotCB.filter())
    async def pick_propose_slot(
        callback_query: CallbackQuery, callback_data: ClientBookSlotCB, state: FSMContext, current_user: User,
    ):
        await ah.apply_picked_propose_slot(
            callback_query, callback_data, state,
            confirm_state=BookingNegotiationStates.confirm_propose_datetime,
            confirm_kb_builder=lambda appointment_id: booking_request_confirm_propose_kb(
                appointment_id, lang=current_user.language,
            ),
            lang=current_user.language,
        )

    @router.callback_query(BookingRequestActionCB.filter(F.action == "retry_propose_datetime"))
    async def retry_propose_datetime(
        callback_query: CallbackQuery, callback_data: BookingRequestActionCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        if DATA_PARSE_MODE.get(instance) == "slots":
            await ah.render_propose_calendar_start(
                callback_query, state, callback_data.appointment_id,
                choose_day_state=BookingNegotiationStates.choose_day, cb_class=BookingRequestActionCB,
                today=get_current_tashkent_datetime().date(), lang=lang,
            )
            return

        await state.set_state(BookingNegotiationStates.propose_datetime)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            _ASK_NEW_DATETIME.get(lang, _ASK_NEW_DATETIME["ru"]),
            reply_markup=booking_request_propose_cancel_kb(callback_data.appointment_id, lang=lang),
        )

    @router.callback_query(BookingRequestActionCB.filter(F.action == "cancel_propose"))
    async def cancel_propose(
        callback_query: CallbackQuery, callback_data: BookingRequestActionCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        await state.clear()
        appointment = await appt_mng.get_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id)
        if appointment is None:
            await callback_query.answer(_REQUEST_NOT_FOUND_DOT.get(lang, _REQUEST_NOT_FOUND_DOT["ru"]), show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_appointment_card(appointment, lang),
            reply_markup=booking_request_kb(callback_data.appointment_id, lang=lang),
        )

    @router.callback_query(BookingRequestActionCB.filter(F.action == "approve_propose_datetime"))
    async def approve_propose_datetime(
        callback_query: CallbackQuery, callback_data: BookingRequestActionCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        data = await state.get_data()
        parsed_dt = data.get("appointment_datetime_parsed")

        if not parsed_dt:
            await callback_query.answer(
                _DATE_PROCESSING_ERROR.get(lang, _DATE_PROCESSING_ERROR["ru"]), show_alert=True,
            )
            return

        db_datetime = format_datetime_for_db(parsed_dt)

        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer(_REQUEST_NOT_FOUND.get(lang, _REQUEST_NOT_FOUND["ru"]), show_alert=True)
            return

        try:
            appointment = await appt_mng.propose_new_datetime(
                callback_data.appointment_id, callback_query.from_user.id, db_datetime, kind="booking",
            )
        except AppointmentNotFoundError:
            await callback_query.answer(_REQUEST_NOT_FOUND.get(lang, _REQUEST_NOT_FOUND["ru"]), show_alert=True)
            return
        except AppointmentAlreadyDecidedError as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
            await invalidate_own_stale_booking_message(callback_query, e, lang)
            await state.clear()
            return
        except ValidationError as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(_GENERIC_ERROR.get(lang, _GENERIC_ERROR["ru"]).format(error=e.localized(lang)), show_alert=True)
            return

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

        if appointment.status == AppointmentStatus.CONFIRMED:
            await callback_query.answer(_TIME_CHANGED.get(lang, _TIME_CHANGED["ru"]))
            await callback_query.message.edit_text(
                _TIME_CHANGED_TO.get(lang, _TIME_CHANGED_TO["ru"]).format(
                    value=_format_datetime_value(appointment.datetime, lang),
                )
            )
            await invalidate_booking_siblings(callback_query, appointment)
            await notify_staff_booking_decision(callback_query, appointment, confirmed=True, lang=lang)
            await state.clear()
            return

        if notification_service:
            try:
                message_id = await notification_service.notify_client_appointment_with_buttons(
                    appointment, rescheduled=True,
                )
                if message_id:
                    await appt_mng.update_notification_message_id(appointment.id, message_id)
            except Exception as e:
                logger.warning(
                    f"Failed to notify client about new pending time for appointment {callback_data.appointment_id}: {e}"
                )

        await callback_query.answer(_TIME_CHANGED_AND_NOTIFIED.get(lang, _TIME_CHANGED_AND_NOTIFIED["ru"]))
        await callback_query.message.edit_text(
            _NEW_TIME_ASSIGNED.get(lang, _NEW_TIME_ASSIGNED["ru"]).format(
                value=_format_datetime_value(appointment.datetime, lang),
            )
        )
        await invalidate_booking_siblings(callback_query, appointment)
        await state.clear()

    async def notify_client_confirmed(appointment) -> None:
        if not notification_service:
            return

        try:
            message_id = await notification_service.notify_client_appointment_with_buttons(
                appointment, use_invite_kb=False
            )
            if message_id:
                await appt_mng.update_notification_message_id(appointment.id, message_id)
        except Exception as e:
            logger.warning(
                f"Failed to notify client about confirmation for appointment {appointment.id}: {e}"
            )

    return router
