import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.appointment_exceptions import AppointmentNotFoundError
from bot.exceptions.exceptions import BotException, PaginationError
from bot.handlers.utils.client_utils.appointment_history_helpers import (
    build_history_card_text,
)
from bot.handlers.utils.client_utils.appointment_log_details_helpers import (
    build_client_appointment_log_details,
)
from bot.handlers.utils.medical_record_delivery import (
    add_medical_record_document,
    deliver_medical_record,
)
from bot.handlers.utils.staff_log_delivery_helpers import record_staff_log_delivery
from bot.keyboards.admin.record_management_kb.appointment_log_details_cb import (
    AppointmentLogDetailsCB,
    AppointmentLogHideDetailsCB,
)
from bot.keyboards.admin.record_management_kb.appointment_log_details_kb import (
    appointment_log_details_kb,
    appointment_log_hide_details_kb,
)
from bot.keyboards.client.appointment_history_cb import (
    ClientHistoryActionCB,
    ClientHistoryCardCB,
    ClientHistoryPageCB,
)
from bot.keyboards.client.appointment_history_kb import (
    appointment_history_card_kb,
    appointment_history_list_kb,
)
from bot.keyboards.client.appointment_manage_cb import (
    ClientManageActionCB,
    ClientManageCardCB,
    ClientManagePageCB,
)
from bot.keyboards.client.appointment_manage_kb import (
    appointment_manage_card_kb,
    appointment_manage_empty_kb,
    appointment_manage_list_kb,
)
from bot.keyboards.client.appointment_management_kb import (
    client_appointment_management_kb,
)
from bot.keyboards.client.appointment_response_kb import (
    appointment_response_kb,
    cancel_confirmation_kb,
)
from bot.models.user import User
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import (
    AppointmentNotificationService,
)
from bot.services.appointment.appointment_pagination_service import (
    AppointmentPaginationService,
)
from bot.services.utils.date_parser import (
    get_current_tashkent_datetime,
    is_appointment_upcoming,
)
from bot.states.client.appointment_states import AppointmentResponseStates
from bot.utils.appointment_enums import (
    APPOINTMENT_TAB_ORDER,
    AppointmentStatus,
    tab_label,
)
from bot.utils.role import RoleFilter

logger = logging.getLogger(__name__)

_HISTORY_TAB_STATUSES = {status.value: status for status in APPOINTMENT_TAB_ORDER}


def _history_tab_title(tab: str, lang: str) -> str | None:
    status = _HISTORY_TAB_STATUSES.get(tab)
    if status is None:
        return None
    return tab_label(status, lang)

_CHOOSE_ACTION_PROMPT = {
    "ru": "Выберите действие:",
    "uz": "Amalni tanlang:",
}

_CONFIRM_IRREVERSIBLE_PROMPT = {
    "ru": "Вы уверены? Это действие нельзя отменить.",
    "uz": "Ishonchingiz komilmi? Bu amalni bekor qilib bo'lmaydi.",
}

_APPOINTMENT_CANCELLED = {
    "ru": "✅ Ваша запись отменена",
    "uz": "✅ Yozuvingiz bekor qilindi",
}

_UNKNOWN_CLIENT_LABEL = {
    "ru": "Неизвестный клиент",
    "uz": "Noma'lum mijoz",
}

_CANCELLED_BY_CLIENT_OUTCOME = {
    "ru": "клиент отменил запись",
    "uz": "mijoz yozuvni bekor qildi",
}

# Клавиатуры заявок, которые отмена клиентом делает нерабочими: "booking" — кнопки
# «Подтвердить/Отклонить» на самозаписи, "reschedule" — «Принять/Отклонить перенос».
# Обе разом, потому что перенос мог быть запрошен по уже подтверждённой записи.
_CLIENT_CANCELLABLE_REQUEST_KINDS = ("booking", "reschedule")

_PROPOSAL_ACCEPTED = {
    "ru": "✅ Вы согласились на новое время. Запись подтверждена.",
    "uz": "✅ Siz yangi vaqtga rozi bo'ldingiz. Yozuv tasdiqlandi.",
}

_PROPOSAL_REJECTED = {
    "ru": (
        "❌ Вы отклонили предложенное время. Если запись всё ещё нужна, "
        "свяжитесь с клиникой или отправьте новую заявку."
    ),
    "uz": (
        "❌ Siz taklif qilingan vaqtni rad etdingiz. Agar yozuv hali ham kerak bo'lsa, "
        "klinika bilan bog'laning yoki yangi ariza yuboring."
    ),
}

_APPOINTMENT_NOT_FOUND = {
    "ru": "Запись не найдена",
    "uz": "Yozuv topilmadi",
}

_APPOINTMENT_NOT_FOUND_DOT = {
    "ru": "Запись не найдена.",
    "uz": "Yozuv topilmadi.",
}

_FEATURE_UNAVAILABLE = {
    "ru": "Функция недоступна.",
    "uz": "Funksiya mavjud emas.",
}

_EDIT_ERROR = {
    "ru": "Ошибка редактирования сообщения",
    "uz": "Xabarni tahrirlashda xatolik",
}

_UNEXPECTED_ERROR = {
    "ru": "Произошла непредвиденная ошибка",
    "uz": "Kutilmagan xatolik yuz berdi",
}

_NO_ACTIVE_APPOINTMENTS = {
    "ru": "У вас нет активных записей.",
    "uz": "Sizda faol yozuvlar yo'q.",
}

_APPOINTMENT_CONFIRMED = {
    "ru": "✅ Спасибо! Ваша запись подтверждена",
    "uz": "✅ Rahmat! Yozuvingiz tasdiqlandi",
}

_INVALID_APPOINTMENT = {
    "ru": "Некорректная запись.",
    "uz": "Noto'g'ri yozuv.",
}

_CANCEL_UNDONE = {
    "ru": "Отмена отменена",
    "uz": "Bekor qilish bekor qilindi",
}

_DEFAULT_HISTORY_TITLE = {
    "ru": "📖 История записей",
    "uz": "📖 Yozuvlar tarixi",
}

_ACTIVE_APPOINTMENTS_TITLE = {
    "ru": "🔧 Активные записи",
    "uz": "🔧 Faol yozuvlar",
}

_PAGE_LABEL = {
    "ru": "({page} из {total})",
    "uz": "({page} / {total})",
}

_TOTAL_LABEL = {
    "ru": "Всего: {count}",
    "uz": "Jami: {count}",
}


def _list_header(title: str, current_page: int, total_pages: int, total_count: int, lang: str) -> str:
    page_label = _PAGE_LABEL.get(lang, _PAGE_LABEL["ru"]).format(page=current_page, total=total_pages)
    total_label = _TOTAL_LABEL.get(lang, _TOTAL_LABEL["ru"]).format(count=total_count)
    return f"{title} {page_label} | {total_label}"


def create_client_appointment_router(
    appointment_pagination_service: AppointmentPaginationService,
    appointment_management_service: AppointmentManagement = None,
    notification_service: AppointmentNotificationService = None,
    appointment_scheduler=None,
    medical_record_service=None,
) -> Router:
    router = Router()

    pagination_service = appointment_pagination_service

    router.message.filter(RoleFilter("client"))
    router.callback_query.filter(RoleFilter("client"))

    async def close_staff_request_keyboards(appointment_id: int, outcome_text: dict[str, str]) -> None:
        """Стереть у сотрудников клавиатуры заявок, которые действие клиента сделало
        нерабочими.

        Без этого после отмены клиентом у каждого сотрудника остаётся живая кнопка
        «Подтвердить/Отклонить»: нажатие уходит в _ensure_not_finalized и возвращает
        popup-ошибку, но само сообщение остаётся выглядеть действующим, и сотрудник
        жмёт его снова.

        Не переиспользует invalidate_sibling_notifications: тот подписывает, КТО из
        сотрудников принял решение, а здесь решения сотрудника нет вовсе.
        actor_chat_id=0 — исключать некого, гасим все записанные сообщения.

        Best-effort: сбой на одном получателе не должен помешать остальным.
        """
        if not notification_service or not appointment_management_service:
            return

        for kind in _CLIENT_CANCELLABLE_REQUEST_KINDS:
            try:
                targets = await appointment_management_service.get_invalidation_targets(
                    appointment_id, kind, actor_chat_id=0
                )
            except Exception as e:
                logger.warning(
                    f"Failed to resolve {kind} invalidation targets for appointment {appointment_id}: {e}"
                )
                continue

            for target in targets:
                try:
                    await notification_service.invalidate_closed_request_message(
                        target.chat_id, target.message_id, outcome_text,
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to close staff {kind} keyboard in chat {target.chat_id} "
                        f"for appointment {appointment_id}: {e}"
                    )

    @router.message(F.text.in_({
        "/appointments", "/book", "/history", "📋 Управление записями", "📋 Yozuvlarni boshqarish",
    }))
    async def show_appointment_management(message: Message, current_user: User):
        await message.answer(
            _CHOOSE_ACTION_PROMPT.get(current_user.language, _CHOOSE_ACTION_PROMPT["ru"]),
            reply_markup=client_appointment_management_kb(current_user.language)
        )

    @router.callback_query(F.data == "client_appointment_history")
    async def appointment_history(callback_query: CallbackQuery, current_user: User):
        await render_history_list(callback_query, tab="confirmed", page=1, lang=current_user.language)

    @router.callback_query(ClientHistoryPageCB.filter())
    async def history_paginate(
        callback_query: CallbackQuery, callback_data: ClientHistoryPageCB, current_user: User,
    ):
        await render_history_list(callback_query, callback_data.tab, callback_data.page, lang=current_user.language)

    @router.callback_query(ClientHistoryCardCB.filter())
    async def history_open_card(
        callback_query: CallbackQuery, callback_data: ClientHistoryCardCB, state: FSMContext, current_user: User,
    ):
        await render_history_card(
            callback_query, callback_data.appointment_id, callback_data.tab, callback_data.page, state,
            current_user.language,
        )

    @router.callback_query(F.data == "client_appointment_menu")
    async def back_to_appointment_menu(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        await state.clear()
        await callback_query.answer('')
        await callback_query.message.edit_text(
            _CHOOSE_ACTION_PROMPT.get(current_user.language, _CHOOSE_ACTION_PROMPT["ru"]),
            reply_markup=client_appointment_management_kb(current_user.language),
        )

    @router.callback_query(F.data == "noop")
    async def noop_button(callback_query: CallbackQuery):
        await callback_query.answer()

    if appointment_management_service:
        @router.callback_query(AppointmentLogDetailsCB.filter())
        async def handle_appointment_log_details(
            callback_query: CallbackQuery, callback_data: AppointmentLogDetailsCB, current_user: User,
        ):
            lang = current_user.language
            appointment = await appointment_management_service.get_appointment_for_client(
                callback_data.appointment_id, callback_query.from_user.id,
            )
            if appointment is None or appointment.client_id != current_user.ID:
                await callback_query.answer(
                    _APPOINTMENT_NOT_FOUND_DOT.get(lang, _APPOINTMENT_NOT_FOUND_DOT["ru"]), show_alert=True,
                )
                return

            notification = await appointment_management_service.get_notification_for_message(
                appointment.id,
                callback_query.message.chat.id,
                callback_query.message.message_id,
                "client_log",
            )
            if (
                notification is None
                or notification.appointment_id != appointment.id
                or notification.chat_id != callback_query.message.chat.id
                or notification.message_id != callback_query.message.message_id
                or notification.kind != "client_log"
                or notification.compact_text is None
            ):
                await callback_query.answer(
                    _APPOINTMENT_NOT_FOUND_DOT.get(lang, _APPOINTMENT_NOT_FOUND_DOT["ru"]), show_alert=True,
                )
                return

            await callback_query.answer("")
            await callback_query.message.edit_text(
                build_client_appointment_log_details(appointment, lang),
                reply_markup=appointment_log_hide_details_kb(appointment.id, lang),
            )

        @router.callback_query(AppointmentLogHideDetailsCB.filter())
        async def handle_appointment_log_hide_details(
            callback_query: CallbackQuery, callback_data: AppointmentLogHideDetailsCB, current_user: User,
        ):
            lang = current_user.language
            appointment = await appointment_management_service.get_appointment_for_client(
                callback_data.appointment_id, callback_query.from_user.id,
            )
            if appointment is None or appointment.client_id != current_user.ID:
                await callback_query.answer(
                    _APPOINTMENT_NOT_FOUND_DOT.get(lang, _APPOINTMENT_NOT_FOUND_DOT["ru"]), show_alert=True,
                )
                return

            notification = await appointment_management_service.get_notification_for_message(
                appointment.id,
                callback_query.message.chat.id,
                callback_query.message.message_id,
                "client_log",
            )
            if (
                notification is None
                or notification.appointment_id != appointment.id
                or notification.chat_id != callback_query.message.chat.id
                or notification.message_id != callback_query.message.message_id
                or notification.kind != "client_log"
                or notification.compact_text is None
            ):
                await callback_query.answer(
                    _APPOINTMENT_NOT_FOUND_DOT.get(lang, _APPOINTMENT_NOT_FOUND_DOT["ru"]), show_alert=True,
                )
                return

            await callback_query.answer("")
            await callback_query.message.edit_text(
                notification.compact_text,
                reply_markup=appointment_log_details_kb(appointment.id, lang),
            )

    # Handler for appointment confirmation
    if appointment_management_service and notification_service:
        @router.callback_query(F.data == "client_manage_appointment")
        async def manage_appointment(callback_query: CallbackQuery, current_user: User):
            await render_manage_list(callback_query, page=1, lang=current_user.language)

        @router.callback_query(ClientManagePageCB.filter())
        async def manage_paginate(
            callback_query: CallbackQuery, callback_data: ClientManagePageCB, current_user: User,
        ):
            await render_manage_list(callback_query, callback_data.page, lang=current_user.language)

        @router.callback_query(ClientManageCardCB.filter())
        async def manage_open_card(
            callback_query: CallbackQuery, callback_data: ClientManageCardCB, state: FSMContext, current_user: User,
        ):
            await render_manage_card(
                callback_query, callback_data.appointment_id, callback_data.page, state, current_user.language,
            )

        async def close_stale_proposal_message(
            appointment_id: int,
            stale_message_id: int | None,
            telegram_user_id: int,
            current_message_id: int | None,
        ) -> None:
            if not stale_message_id:
                return

            await appointment_management_service.update_proposal_message_id(appointment_id, None)

            if stale_message_id == current_message_id:
                # The client answered directly on the proposal message itself,
                # which was just edited to show the success/rejection text above.
                # Closing it here would overwrite that text.
                return

            try:
                await notification_service.close_reschedule_proposal_message(
                    telegram_user_id, stale_message_id
                )
            except Exception:
                pass

        @router.callback_query(ClientManageActionCB.filter())
        async def manage_action(
            callback_query: CallbackQuery, callback_data: ClientManageActionCB, state: FSMContext, current_user: User,
        ):
            lang = current_user.language
            appointment_id = callback_data.appointment_id
            page = callback_data.page

            if callback_data.action == "cancel_ask":
                await callback_query.message.edit_text(
                    _CONFIRM_IRREVERSIBLE_PROMPT.get(lang, _CONFIRM_IRREVERSIBLE_PROMPT["ru"]),
                    reply_markup=cancel_confirmation_kb(
                        yes_callback=ClientManageActionCB(
                            action="cancel_yes", appointment_id=appointment_id, page=page
                        ).pack(),
                        no_callback=ClientManageActionCB(
                            action="cancel_no", appointment_id=appointment_id, page=page
                        ).pack(),
                        lang=lang,
                    ),
                )
                await callback_query.answer()
                return

            if callback_data.action == "cancel_yes":
                try:
                    await appointment_management_service.cancel_appointment_by_client(
                        appointment_id, callback_query.from_user.id, enforce_cutoff=True
                    )

                    appointment, client = await appointment_management_service.get_appointment_with_client_info(
                        appointment_id
                    )

                    if appointment_scheduler:
                        await appointment_scheduler.cancel_all_jobs(appointment_id)

                    await callback_query.message.edit_text(_APPOINTMENT_CANCELLED.get(lang, _APPOINTMENT_CANCELLED["ru"]))
                    await callback_query.answer()

                    if notification_service:
                        try:
                            recipients = await appointment_management_service.resolve_notification_recipients(
                                appointment
                            )
                        except Exception:
                            recipients = []
                        for recipient in recipients:
                            try:
                                delivery = await notification_service.notify_admin_cancellation(
                                    recipient.telegram_user_id,
                                    appointment,
                                    client.full_name if client else _UNKNOWN_CLIENT_LABEL.get(lang, _UNKNOWN_CLIENT_LABEL["ru"]),
                                )
                                await record_staff_log_delivery(
                                    appointment_management_service,
                                    notification_service.notifier,
                                    appointment_id=appointment.id,
                                    chat_id=recipient.telegram_user_id,
                                    kind="cancellation",
                                    delivery=delivery,
                                )
                            except Exception:
                                pass  # Graceful fail если не получилось отправить

                    await close_staff_request_keyboards(appointment_id, _CANCELLED_BY_CLIENT_OUTCOME)
                except AppointmentNotFoundError:
                    await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
                except BotException as e:
                    await callback_query.answer(e.localized(lang), show_alert=True)
                return

            if callback_data.action == "cancel_no":
                await render_manage_card(callback_query, appointment_id, page, state, lang)
                return

            if callback_data.action == "accept_proposal":
                try:
                    pre_mutation_appointment = await appointment_management_service.get_appointment_for_client(
                        appointment_id, callback_query.from_user.id,
                    )
                    appointment = await appointment_management_service.accept_proposed_datetime(
                        appointment_id, callback_query.from_user.id
                    )
                    stale_message_id = appointment.proposal_message_id

                    _, client = await appointment_management_service.get_appointment_with_client_info(
                        appointment_id
                    )

                    if appointment_scheduler:
                        await appointment_scheduler.resync_appointment_jobs(appointment)

                    await callback_query.message.edit_text(
                        _PROPOSAL_ACCEPTED.get(lang, _PROPOSAL_ACCEPTED["ru"])
                    )
                    await callback_query.answer()

                    await close_stale_proposal_message(
                        appointment_id,
                        stale_message_id,
                        callback_query.from_user.id,
                        callback_query.message.message_id,
                    )

                    if notification_service:
                        try:
                            recipients = await appointment_management_service.resolve_notification_recipients(
                                appointment
                            )
                        except Exception:
                            recipients = []
                        kind = (
                            appointment_management_service.resolve_admin_proposal_log_kind(
                                pre_mutation_appointment,
                            )
                            if pre_mutation_appointment
                            else None
                        )
                        for recipient in recipients:
                            try:
                                delivery = await notification_service.notify_staff_proposal_accepted(
                                    recipient.telegram_user_id,
                                    appointment,
                                    client.full_name if client else _UNKNOWN_CLIENT_LABEL.get(lang, _UNKNOWN_CLIENT_LABEL["ru"]),
                                )
                                if kind:
                                    await record_staff_log_delivery(
                                        appointment_management_service,
                                        notification_service.notifier,
                                        appointment_id=appointment.id,
                                        chat_id=recipient.telegram_user_id,
                                        kind=kind,
                                        delivery=delivery,
                                    )
                            except Exception:
                                pass  # Graceful fail если не получилось отправить
                except AppointmentNotFoundError:
                    await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
                except BotException as e:
                    await callback_query.answer(e.localized(lang), show_alert=True)
                return

            if callback_data.action == "reject_proposal":
                try:
                    pre_mutation_appointment = await appointment_management_service.get_appointment_for_client(
                        appointment_id, callback_query.from_user.id,
                    )
                    appointment = await appointment_management_service.reject_proposed_datetime(
                        appointment_id, callback_query.from_user.id
                    )
                    stale_message_id = appointment.proposal_message_id

                    _, client = await appointment_management_service.get_appointment_with_client_info(
                        appointment_id
                    )

                    if appointment_scheduler:
                        await appointment_scheduler.resync_appointment_jobs(appointment)

                    await callback_query.message.edit_text(
                        _PROPOSAL_REJECTED.get(lang, _PROPOSAL_REJECTED["ru"])
                    )
                    await callback_query.answer()

                    await close_stale_proposal_message(
                        appointment_id,
                        stale_message_id,
                        callback_query.from_user.id,
                        callback_query.message.message_id,
                    )

                    if notification_service:
                        try:
                            recipients = await appointment_management_service.resolve_notification_recipients(
                                appointment
                            )
                        except Exception:
                            recipients = []
                        kind = (
                            appointment_management_service.resolve_admin_proposal_log_kind(
                                pre_mutation_appointment,
                            )
                            if pre_mutation_appointment
                            else None
                        )
                        for recipient in recipients:
                            try:
                                delivery = await notification_service.notify_staff_proposal_rejected(
                                    recipient.telegram_user_id,
                                    appointment,
                                    client.full_name if client else _UNKNOWN_CLIENT_LABEL.get(lang, _UNKNOWN_CLIENT_LABEL["ru"]),
                                )
                                if kind:
                                    await record_staff_log_delivery(
                                        appointment_management_service,
                                        notification_service.notifier,
                                        appointment_id=appointment.id,
                                        chat_id=recipient.telegram_user_id,
                                        kind=kind,
                                        delivery=delivery,
                                    )
                            except Exception:
                                pass  # Graceful fail если не получилось отправить
                except AppointmentNotFoundError:
                    await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
                except BotException as e:
                    await callback_query.answer(e.localized(lang), show_alert=True)
                return

        @router.callback_query(ClientHistoryActionCB.filter())
        async def history_action(
            callback_query: CallbackQuery, callback_data: ClientHistoryActionCB, state: FSMContext, current_user: User,
        ):
            lang = current_user.language
            appointment_id = callback_data.appointment_id
            tab = callback_data.tab
            page = callback_data.page

            if callback_data.action == "cancel_ask":
                await callback_query.message.edit_text(
                    _CONFIRM_IRREVERSIBLE_PROMPT.get(lang, _CONFIRM_IRREVERSIBLE_PROMPT["ru"]),
                    reply_markup=cancel_confirmation_kb(
                        yes_callback=ClientHistoryActionCB(
                            action="cancel_yes", appointment_id=appointment_id, tab=tab, page=page,
                        ).pack(),
                        no_callback=ClientHistoryActionCB(
                            action="cancel_no", appointment_id=appointment_id, tab=tab, page=page,
                        ).pack(),
                        lang=lang,
                    ),
                )
                await callback_query.answer()
                return

            if callback_data.action == "cancel_yes":
                try:
                    await appointment_management_service.cancel_appointment_by_client(
                        appointment_id, callback_query.from_user.id, enforce_cutoff=True
                    )

                    appointment, client = await appointment_management_service.get_appointment_with_client_info(
                        appointment_id
                    )

                    if appointment_scheduler:
                        await appointment_scheduler.cancel_all_jobs(appointment_id)

                    if notification_service:
                        try:
                            recipients = await appointment_management_service.resolve_notification_recipients(
                                appointment
                            )
                        except Exception:
                            recipients = []
                        for recipient in recipients:
                            try:
                                delivery = await notification_service.notify_admin_cancellation(
                                    recipient.telegram_user_id,
                                    appointment,
                                    client.full_name if client else _UNKNOWN_CLIENT_LABEL.get(lang, _UNKNOWN_CLIENT_LABEL["ru"]),
                                )
                                await record_staff_log_delivery(
                                    appointment_management_service,
                                    notification_service.notifier,
                                    appointment_id=appointment.id,
                                    chat_id=recipient.telegram_user_id,
                                    kind="cancellation",
                                    delivery=delivery,
                                )
                            except Exception:
                                pass  # Graceful fail если не получилось отправить

                    await close_staff_request_keyboards(appointment_id, _CANCELLED_BY_CLIENT_OUTCOME)

                    await render_history_card(callback_query, appointment_id, tab, page, state, lang)
                except AppointmentNotFoundError:
                    await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
                except BotException as e:
                    await callback_query.answer(e.localized(lang), show_alert=True)
                return

            if callback_data.action == "cancel_no":
                await render_history_card(callback_query, appointment_id, tab, page, state, lang)
                return

            if callback_data.action == "get_medical_record":
                if not medical_record_service:
                    await callback_query.answer(_FEATURE_UNAVAILABLE.get(lang, _FEATURE_UNAVAILABLE["ru"]), show_alert=True)
                    return

                appointment = await appointment_management_service.get_appointment_for_client(
                    appointment_id, callback_query.from_user.id,
                )
                if appointment is None:
                    await callback_query.answer(_APPOINTMENT_NOT_FOUND_DOT.get(lang, _APPOINTMENT_NOT_FOUND_DOT["ru"]), show_alert=True)
                    return

                await deliver_medical_record(callback_query, medical_record_service, appointment_id, lang=lang)
                return

            if callback_data.action == "add_medical_record":
                if not medical_record_service:
                    await callback_query.answer(_FEATURE_UNAVAILABLE.get(lang, _FEATURE_UNAVAILABLE["ru"]), show_alert=True)
                    return

                appointment = await appointment_management_service.get_appointment_for_client(
                    appointment_id, callback_query.from_user.id,
                )
                if appointment is None:
                    await callback_query.answer(_APPOINTMENT_NOT_FOUND_DOT.get(lang, _APPOINTMENT_NOT_FOUND_DOT["ru"]), show_alert=True)
                    return

                await add_medical_record_document(
                    callback_query, medical_record_service, appointment_id, appointment.purpose, lang=lang,
                )
                return

        @router.callback_query(F.data.startswith("appt_confirm:"))
        async def handle_appointment_confirm(callback_query: CallbackQuery, current_user: User):
            """Handle appointment confirmation button."""
            lang = current_user.language
            try:
                appointment_id = int(callback_query.data.split(":")[1])

                # Update status to CONFIRMED
                appointment = await appointment_management_service.confirm_appointment_by_client(
                    appointment_id, callback_query.from_user.id
                )

                # Get appointment info for job resync
                appointment, _ = await appointment_management_service.get_appointment_with_client_info(
                    appointment_id
                )

                if appointment_scheduler:
                    await appointment_scheduler.resync_appointment_jobs(appointment)

                # Send success message to client
                await callback_query.message.edit_text(_APPOINTMENT_CONFIRMED.get(lang, _APPOINTMENT_CONFIRMED["ru"]))
                await callback_query.answer()

            except ValueError:
                await callback_query.answer(_INVALID_APPOINTMENT.get(lang, _INVALID_APPOINTMENT["ru"]), show_alert=True)
            except AppointmentNotFoundError:
                await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
            except BotException as e:
                await callback_query.answer(e.localized(lang), show_alert=True)

        @router.callback_query(F.data.startswith("appt_details:"))
        async def handle_appointment_details(callback_query: CallbackQuery, current_user: User):
            """Handle appointment details button (rebuild full card on the original message)."""
            lang = current_user.language
            try:
                appointment_id = int(callback_query.data.split(":")[1])
            except ValueError:
                await callback_query.answer(_INVALID_APPOINTMENT.get(lang, _INVALID_APPOINTMENT["ru"]), show_alert=True)
                return

            appointment = await appointment_management_service.get_appointment_for_client(
                appointment_id, callback_query.from_user.id,
            )
            if appointment is None:
                await callback_query.answer(_APPOINTMENT_NOT_FOUND_DOT.get(lang, _APPOINTMENT_NOT_FOUND_DOT["ru"]), show_alert=True)
                return

            await notification_service.notify_client_appointment_details(appointment)
            await callback_query.answer()

        # Handler for appointment cancellation (shows confirmation dialog)
        @router.callback_query(F.data.startswith("appt_cancel:"))
        async def handle_appointment_cancel(callback_query: CallbackQuery, state: FSMContext, current_user: User):
            """Handle appointment cancellation button (show confirmation dialog)."""
            lang = current_user.language
            try:
                appointment_id = int(callback_query.data.split(":")[1])

                await state.set_state(AppointmentResponseStates.confirm_cancel)
                await state.update_data(appointment_id=appointment_id)

                await callback_query.message.edit_text(
                    _CONFIRM_IRREVERSIBLE_PROMPT.get(lang, _CONFIRM_IRREVERSIBLE_PROMPT["ru"]),
                    reply_markup=cancel_confirmation_kb(
                        yes_callback="appt_cancel_confirm_yes",
                        no_callback="appt_cancel_confirm_no",
                        lang=lang,
                    ),
                )
                await callback_query.answer()
            except ValueError:
                await callback_query.answer(_INVALID_APPOINTMENT.get(lang, _INVALID_APPOINTMENT["ru"]), show_alert=True)
            except BotException as e:
                await callback_query.answer(e.localized(lang), show_alert=True)

        # Handler for cancellation confirmation YES
        @router.callback_query(AppointmentResponseStates.confirm_cancel, F.data == "appt_cancel_confirm_yes")
        async def handle_cancel_confirmation_yes(callback_query: CallbackQuery, state: FSMContext, current_user: User):
            """Confirm cancellation."""
            lang = current_user.language
            try:
                data = await state.get_data()
                appointment_id = data.get("appointment_id")

                # Update status to CANCELLED (1h cutoff does not apply to the
                # reminder-triggered flow)
                appointment = await appointment_management_service.cancel_appointment_by_client(
                    appointment_id, callback_query.from_user.id, enforce_cutoff=False
                )

                # Get appointment and client info for notification
                appointment, client = await appointment_management_service.get_appointment_with_client_info(
                    appointment_id
                )

                if appointment_scheduler:
                    await appointment_scheduler.cancel_all_jobs(appointment_id)

                await callback_query.message.edit_text(_APPOINTMENT_CANCELLED.get(lang, _APPOINTMENT_CANCELLED["ru"]))
                await callback_query.answer()

                # Notify admin about cancellation
                if notification_service:
                    try:
                        recipients = await appointment_management_service.resolve_notification_recipients(appointment)
                    except Exception:
                        recipients = []
                    for recipient in recipients:
                        try:
                            delivery = await notification_service.notify_admin_cancellation(
                                recipient.telegram_user_id,
                                appointment,
                                client.full_name if client else _UNKNOWN_CLIENT_LABEL.get(lang, _UNKNOWN_CLIENT_LABEL["ru"]),
                            )
                            await record_staff_log_delivery(
                                appointment_management_service,
                                notification_service.notifier,
                                appointment_id=appointment.id,
                                chat_id=recipient.telegram_user_id,
                                kind="cancellation",
                                delivery=delivery,
                            )
                        except Exception:
                            pass  # Graceful fail если не получилось отправить

                await close_staff_request_keyboards(appointment_id, _CANCELLED_BY_CLIENT_OUTCOME)

            except AppointmentNotFoundError:
                await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
            except BotException as e:
                await callback_query.answer(e.localized(lang), show_alert=True)
            finally:
                await state.clear()

        # Handler for cancellation confirmation NO
        @router.callback_query(AppointmentResponseStates.confirm_cancel, F.data == "appt_cancel_confirm_no")
        async def handle_cancel_confirmation_no(callback_query: CallbackQuery, state: FSMContext, current_user: User):
            """Cancel the cancellation (go back)."""
            lang = current_user.language
            try:
                data = await state.get_data()
                appointment_id = data.get("appointment_id")

                await callback_query.message.edit_text(
                    _CANCEL_UNDONE.get(lang, _CANCEL_UNDONE["ru"]),
                    reply_markup=appointment_response_kb(appointment_id, lang),
                )
                await callback_query.answer()
            except BotException as e:
                await callback_query.answer(e.localized(lang), show_alert=True)
            finally:
                await state.clear()

    async def render_history_list(callback_query: CallbackQuery, tab: str, page: int, lang: str = "ru") -> None:
        try:
            result = await pagination_service.paginate_client_appointments(
                callback_query.from_user.id, tab, page,
            )

            title = _history_tab_title(tab, lang) or _DEFAULT_HISTORY_TITLE.get(lang, _DEFAULT_HISTORY_TITLE["ru"])
            text = _list_header(title, result.current_page, result.total_pages, result.total_count, lang)

            await callback_query.message.edit_text(
                text,
                reply_markup=appointment_history_list_kb(
                    result.items, tab, result.current_page, result.total_pages, lang,
                ),
            )
            await callback_query.answer()
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback_query.answer()
            else:
                logger.warning(f"TelegramBadRequest in render_history_list: {e}")
                await callback_query.answer(_EDIT_ERROR.get(lang, _EDIT_ERROR["ru"]), show_alert=False)
        except PaginationError as e:
            logger.warning(f"Pagination error in render_history_list: {e}")
            await callback_query.answer(e.localized(lang), show_alert=True)
        except Exception as e:
            logger.exception(f"Unexpected error in render_history_list: {e}")
            await callback_query.answer(_UNEXPECTED_ERROR.get(lang, _UNEXPECTED_ERROR["ru"]), show_alert=True)

    async def render_history_card(
        callback_query: CallbackQuery, appointment_id: int, tab: str, page: int, state: FSMContext, lang: str = "ru",
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

        await state.update_data(origin="history", tab=tab, page=page)

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_history_card_text(appointment, lang),
            reply_markup=appointment_history_card_kb(appointment, tab, page, can_cancel, can_reschedule, lang),
        )

    async def render_manage_list(callback_query: CallbackQuery, page: int, lang: str = "ru") -> None:
        try:
            result = await pagination_service.paginate_active_client_appointments(
                callback_query.from_user.id, page,
            )

            if result.total_count == 0:
                await callback_query.message.edit_text(
                    _NO_ACTIVE_APPOINTMENTS.get(lang, _NO_ACTIVE_APPOINTMENTS["ru"]),
                    reply_markup=appointment_manage_empty_kb(lang),
                )
                await callback_query.answer()
                return

            title = _ACTIVE_APPOINTMENTS_TITLE.get(lang, _ACTIVE_APPOINTMENTS_TITLE["ru"])
            text = _list_header(title, result.current_page, result.total_pages, result.total_count, lang)

            await callback_query.message.edit_text(
                text,
                reply_markup=appointment_manage_list_kb(
                    result.items, result.current_page, result.total_pages, lang,
                ),
            )
            await callback_query.answer()
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback_query.answer()
            else:
                logger.warning(f"TelegramBadRequest in render_manage_list: {e}")
                await callback_query.answer(_EDIT_ERROR.get(lang, _EDIT_ERROR["ru"]), show_alert=False)
        except PaginationError as e:
            logger.warning(f"Pagination error in render_manage_list: {e}")
            await callback_query.answer(e.localized(lang), show_alert=True)
        except Exception as e:
            logger.exception(f"Unexpected error in render_manage_list: {e}")
            await callback_query.answer(_UNEXPECTED_ERROR.get(lang, _UNEXPECTED_ERROR["ru"]), show_alert=True)

    async def render_manage_card(
        callback_query: CallbackQuery, appointment_id: int, page: int, state: FSMContext, lang: str = "ru",
    ) -> None:
        appointment = await appointment_management_service.get_appointment_for_client(
            appointment_id, callback_query.from_user.id,
        )
        if appointment is None:
            await callback_query.answer(_APPOINTMENT_NOT_FOUND_DOT.get(lang, _APPOINTMENT_NOT_FOUND_DOT["ru"]), show_alert=True)
            return

        await state.update_data(origin="manage", page=page)

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_history_card_text(appointment, lang),
            reply_markup=appointment_manage_card_kb(appointment, page, lang),
        )

    return router
