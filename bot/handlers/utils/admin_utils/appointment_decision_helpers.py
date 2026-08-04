from bot.exceptions.appointment_exceptions import AppointmentAlreadyDecidedError
from bot.handlers.utils.admin_utils.appointment_helpers import build_appointment_card
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import AppointmentNotificationService

DEFAULT_DECIDED_BY_LABEL = {
    "ru": "Другой сотрудник",
    "uz": "Boshqa xodim",
}

DEFAULT_OUTCOME_TEXT = {
    "ru": "решение принято",
    "uz": "qaror qabul qilindi",
}


async def invalidate_sibling_notifications(
    notification_service: AppointmentNotificationService,
    appt_mng: AppointmentManagement,
    appointment_id: int,
    kind: str,
    actor_chat_id: int,
    decided_by_label: dict[str, str],
    outcome_text: dict[str, str],
) -> None:
    """Стереть клавиатуры у уведомлений остальных получателей той же заявки.

    Вызывается после того, как один сотрудник принял решение по заявке
    (подтвердил/отклонил/предложил время/завершил приём), чтобы коллеги,
    получившие такое же уведомление, не пытались решить уже решённую заявку.
    Собственное сообщение действующего сотрудника (actor_chat_id) не трогаем —
    оно уже отредактировано обычным success-путём хендлера.
    """
    targets = await appt_mng.get_invalidation_targets(appointment_id, kind, actor_chat_id)

    for target in targets:
        await notification_service.invalidate_stale_decision_message(
            target.chat_id, target.message_id, decided_by_label, outcome_text,
        )


async def invalidate_actor_stale_message(
    notification_service: AppointmentNotificationService,
    error: AppointmentAlreadyDecidedError,
    chat_id: int,
    message_id: int,
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
    appointment_summary = build_appointment_card(error.appointment, lang) if error.appointment else None

    await notification_service.invalidate_stale_decision_message(
        chat_id, message_id, decided_by_label, outcome_text,
        appointment_summary=appointment_summary,
    )
