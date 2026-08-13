import logging

from bot.exceptions.appointment_exceptions import AppointmentAlreadyDecidedError
from bot.handlers.utils.staff_log_delivery_helpers import record_staff_log_delivery
from bot.keyboards.admin.record_management_kb.appointment_log_details_kb import (
    appointment_log_details_kb,
)
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import (
    DEFAULT_UNKNOWN_CLIENT_LABEL,
    AppointmentNotificationService,
    stale_decision_text,
)

logger = logging.getLogger(__name__)

DEFAULT_DECIDED_BY_LABEL = {
    "ru": "Другой сотрудник",
    "uz": "Boshqa xodim",
}

DEFAULT_OUTCOME_TEXT = {
    "ru": "решение принято",
    "uz": "qaror qabul qilindi",
}


def staff_completion_result_text(appointment_id: int, actor_label: str, lang: str) -> str:
    if lang == "uz":
        return f"№{appointment_id} qabul yakunlandi.\nYakunladi: {actor_label}"

    return f"Приём №{appointment_id} завершён.\nЗавершил(а): {actor_label}"


async def persist_compact_notification_text(
    appt_mng: AppointmentManagement,
    appointment_id: int,
    chat_id: int,
    message_id: int,
    kind: str,
    compact_text: str,
) -> bool:
    """Persist text only on the callback message's exact notification row."""
    try:
        return await appt_mng.set_notification_compact_text(
            appointment_id, chat_id, message_id, kind, compact_text,
        )
    except Exception as error:  # noqa: BLE001 - UI must fail closed on storage errors.
        logger.warning(
            "Failed to store compact %s text for notification %s: %s",
            kind,
            message_id,
            error,
        )
        return False


async def compact_completion_result(
    appt_mng: AppointmentManagement,
    appointment,
    chat_id: int,
    message_id: int,
    lang: str,
) -> tuple[str, bool]:
    actor_label = await appt_mng.resolve_decision_label(appointment.decided_by_user_id)
    compact_text = staff_completion_result_text(
        appointment.id, actor_label.get(lang, actor_label["ru"]), lang,
    )
    stored = await persist_compact_notification_text(
        appt_mng, appointment.id, chat_id, message_id, "completion", compact_text,
    )
    return compact_text, stored


async def compact_decision_result(
    appt_mng: AppointmentManagement,
    appointment_id: int,
    chat_id: int,
    message_id: int,
    kind: str,
    decided_by_label: dict[str, str],
    outcome_text: dict[str, str],
    lang: str,
) -> tuple[str, bool]:
    compact_text = stale_decision_text(
        decided_by_label.get(lang, decided_by_label["ru"]),
        outcome_text.get(lang, outcome_text["ru"]),
        lang,
    )
    stored = await persist_compact_notification_text(
        appt_mng, appointment_id, chat_id, message_id, kind, compact_text,
    )
    return compact_text, stored


async def replace_completion_sibling_prompts(
    notification_service: AppointmentNotificationService,
    appt_mng: AppointmentManagement,
    appointment,
    actor_chat_id: int,
) -> None:
    """Replace stored colleague completion prompts with a compact result."""
    try:
        actor_label = await appt_mng.resolve_decision_label(appointment.decided_by_user_id)
        targets = await appt_mng.get_invalidation_targets(appointment.id, "completion", actor_chat_id)
    except Exception as error:  # noqa: BLE001 - sibling resolution must not block completion.
        logger.warning("Failed to resolve completion sibling prompts for appointment %s: %s", appointment.id, error)
        return

    for target in targets:
        try:
            lang = await notification_service.resolve_recipient_language(target.chat_id)
            label = actor_label.get(lang, actor_label["ru"])
            compact_text = staff_completion_result_text(appointment.id, label, lang)
            compact_text_stored = await persist_compact_notification_text(
                appt_mng, appointment.id, target.chat_id, target.message_id, "completion", compact_text,
            )
            await notification_service.notifier.try_edit_message_text(
                chat_id=target.chat_id,
                message_id=target.message_id,
                text=compact_text,
                reply_markup=(
                    appointment_log_details_kb(appointment.id, lang)
                    if compact_text_stored is True else None
                ),
            )
        except Exception as error:  # noqa: BLE001 - each sibling edit must be isolated.
            logger.warning("Failed to replace completion sibling prompt %s: %s", target.message_id, error)


async def invalidate_sibling_notifications(
    notification_service: AppointmentNotificationService,
    appt_mng: AppointmentManagement,
    appointment_id: int,
    kind: str,
    actor_chat_id: int,
    decided_by_label: dict[str, str],
    outcome_text: dict[str, str],
    appointment=None,
    lang: str = "ru",
) -> None:
    """Стереть клавиатуры у уведомлений остальных получателей той же заявки.

    Вызывается после того, как один сотрудник принял решение по заявке
    (подтвердил/отклонил/предложил время/завершил приём), чтобы коллеги,
    получившие такое же уведомление, не пытались решить уже решённую заявку.
    Собственное сообщение действующего сотрудника (actor_chat_id) не трогаем —
    оно уже отредактировано обычным success-путём хендлера.

    appointment/lang, if provided, are used to build an appointment card
    (client/phone/time/status) appended below the decision text, the same way
    invalidate_actor_stale_message does for the acting user's own message.
    """
    targets = await appt_mng.get_invalidation_targets(appointment_id, kind, actor_chat_id)
    for target in targets:
        try:
            target_lang = await notification_service.resolve_recipient_language(target.chat_id)
            compact_text, compact_text_stored = await compact_decision_result(
                appt_mng, appointment_id, target.chat_id, target.message_id, kind,
                decided_by_label, outcome_text, target_lang,
            )
            await notification_service.notifier.try_edit_message_text(
                chat_id=target.chat_id,
                message_id=target.message_id,
                text=compact_text,
                reply_markup=(
                    appointment_log_details_kb(appointment_id, target_lang)
                    if compact_text_stored is True else None
                ),
            )
        except Exception as error:  # noqa: BLE001 - each sibling edit must be isolated.
            logger.warning("Failed to replace stale %s notification %s: %s", kind, target.message_id, error)


async def invalidate_actor_stale_message(
    notification_service: AppointmentNotificationService,
    appt_mng: AppointmentManagement,
    error: AppointmentAlreadyDecidedError,
    appointment_id: int,
    chat_id: int,
    message_id: int,
    kind: str,
    lang: str,
) -> None:
    """Стереть клавиатуру у собственного сообщения действующего сотрудника.

    Вызывается при AppointmentAlreadyDecidedError: пока текущий сотрудник
    принимал решение, коллега уже обработал ту же заявку. Метка и текст исхода
    берутся из самого исключения (уже вычислены сервисом при попытке действия),
    чтобы не повторять запрос к БД. Если исключение несёт свежепрочитанную
    заявку, под текстом решения дополнительно показывается её карточка
    (клиент, телефон, время, статус) — этого не умещается в 200-символьный
    show_alert-попап, поэтому переносится в редактируемое сообщение.
    """
    decided_by_label = error.decided_by_label or DEFAULT_DECIDED_BY_LABEL
    outcome_text = error.outcome_text or DEFAULT_OUTCOME_TEXT
    compact_text, compact_text_stored = await compact_decision_result(
        appt_mng, appointment_id, chat_id, message_id, kind, decided_by_label, outcome_text, lang,
    )
    await notification_service.notifier.try_edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=compact_text,
        reply_markup=(
            appointment_log_details_kb(appointment_id, lang)
            if compact_text_stored is True else None
        ),
    )


async def invalidate_own_stale_finalized_message(callback_query, text: str) -> None:
    """Remove the action keyboard when the appointment is already finalized.

    This path has no deciding staff member to report, so it edits the callback
    message directly instead of using the decision-notification invalidation.
    Telegram can reject the edit when the message was deleted or already has
    the same content; neither case should make the callback handler fail.
    """
    try:
        await callback_query.message.edit_text(text, reply_markup=None)
    except Exception as error:
        if "message is not modified" not in str(error):
            logger.warning("Failed to invalidate finalized appointment message: %s", error)


async def notify_staff_reschedule_decision(
    notification_service: AppointmentNotificationService,
    appt_mng: AppointmentManagement,
    actor_telegram_id: int,
    appointment,
    accepted: bool,
    lang: str,
) -> None:
    """Уведомить остальных сотрудников о решении по заявке на перенос.

    Действующий сотрудник (actor_telegram_id) не получает уведомление о
    собственном решении.
    """
    if not notification_service:
        return
    try:
        actor = await appt_mng.get_user_by_telegram_id(actor_telegram_id)
        actor_label = await appt_mng.resolve_decision_label(actor.ID if actor else None)
        client = await appt_mng.get_client_by_id(appointment.client_id)
        client_name = client.full_name if client else DEFAULT_UNKNOWN_CLIENT_LABEL.get(lang, DEFAULT_UNKNOWN_CLIENT_LABEL["ru"])
        recipients = await appt_mng.resolve_notification_recipients(appointment)
    except Exception as e:
        logger.warning(
            f"Failed to resolve staff recipients for reschedule decision on appointment {appointment.id}: {e}"
        )
        return

    for recipient in recipients:
        if recipient.telegram_user_id == actor_telegram_id:
            continue
        try:
            if accepted:
                delivery = await notification_service.notify_staff_reschedule_decision_accepted(
                    recipient.telegram_user_id, appointment, actor_label, client_name,
                )
            else:
                delivery = await notification_service.notify_staff_reschedule_decision_rejected(
                    recipient.telegram_user_id, appointment, actor_label, client_name,
                )
            await record_staff_log_delivery(
                appt_mng,
                notification_service.notifier,
                appointment_id=appointment.id,
                chat_id=recipient.telegram_user_id,
                kind="reschedule",
                delivery=delivery,
            )
        except Exception as e:
            logger.warning(
                f"Failed to notify staff {recipient.telegram_user_id} about reschedule decision "
                f"for appointment {appointment.id}: {e}"
            )


async def notify_staff_appointment_cancellation(
    notification_service: AppointmentNotificationService,
    appt_mng: AppointmentManagement,
    actor_telegram_id: int,
    appointment,
    deleted: bool = False,
    record: bool = True,
) -> None:
    """Уведомить остальных сотрудников об отмене/удалении записи коллегой.

    Действующий сотрудник (actor_telegram_id) не получает уведомление о
    собственном действии. deleted=True переключает формулировку на "удалена"
    (для finish_delete, где строка appointments уже отсутствует) вместо
    "отменена" (для set_status -> CANCELLED, где строка сохраняется).
    record=False пропускает запись в appointment_notifications — используется
    при deleted=True, так как строку appointments, к которой относится FK,
    уже удалили.
    """
    if not notification_service:
        return
    try:
        actor = await appt_mng.get_user_by_telegram_id(actor_telegram_id)
        actor_label = await appt_mng.resolve_decision_label(actor.ID if actor else None)
        client = await appt_mng.get_client_by_id(appointment.client_id)
        client_name = client.full_name if client else None
        recipients = await appt_mng.resolve_notification_recipients(appointment)
    except Exception as e:
        logger.warning(
            f"Failed to resolve staff recipients for cancellation of appointment {appointment.id}: {e}"
        )
        return

    for recipient in recipients:
        if recipient.telegram_user_id == actor_telegram_id:
            continue
        try:
            delivery = await notification_service.notify_staff_appointment_cancelled(
                recipient.telegram_user_id, appointment, actor_label, client_name, deleted=deleted,
            )
            if record:
                await record_staff_log_delivery(
                    appt_mng,
                    notification_service.notifier,
                    appointment_id=appointment.id,
                    chat_id=recipient.telegram_user_id,
                    kind="cancellation",
                    delivery=delivery,
                )
        except Exception as e:
            logger.warning(
                f"Failed to notify staff {recipient.telegram_user_id} about cancellation of "
                f"appointment {appointment.id}: {e}"
            )


async def notify_staff_appointment_creation(
    notification_service: AppointmentNotificationService,
    appt_mng: AppointmentManagement,
    actor_telegram_id: int,
    appointment,
) -> None:
    """Уведомить остальных сотрудников о новой записи, созданной коллегой.

    Действующий сотрудник (actor_telegram_id) не получает уведомление о
    собственном создании записи.
    """
    if not notification_service:
        return
    try:
        actor = await appt_mng.get_user_by_telegram_id(actor_telegram_id)
        actor_label = await appt_mng.resolve_decision_label(actor.ID if actor else None)
        client = await appt_mng.get_client_by_id(appointment.client_id)
        client_name = client.full_name if client else None
        recipients = await appt_mng.resolve_notification_recipients(appointment)
    except Exception as e:
        logger.warning(
            f"Failed to resolve staff recipients for new appointment {appointment.id}: {e}"
        )
        return

    for recipient in recipients:
        if recipient.telegram_user_id == actor_telegram_id:
            continue
        try:
            delivery = await notification_service.notify_staff_appointment_created(
                recipient.telegram_user_id, appointment, actor_label, client_name,
            )
            await record_staff_log_delivery(
                appt_mng,
                notification_service.notifier,
                appointment_id=appointment.id,
                chat_id=recipient.telegram_user_id,
                kind="creation",
                delivery=delivery,
            )
        except Exception as e:
            logger.warning(
                f"Failed to notify staff {recipient.telegram_user_id} about new appointment "
                f"{appointment.id}: {e}"
            )
