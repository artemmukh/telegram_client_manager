from bot.exceptions.appointment_exceptions import AppointmentAlreadyDecidedError
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import AppointmentNotificationService


async def invalidate_sibling_notifications(
    notification_service: AppointmentNotificationService,
    appt_mng: AppointmentManagement,
    appointment_id: int,
    kind: str,
    actor_chat_id: int,
    decided_by_label: str,
    outcome_text: str,
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
) -> None:
    """Стереть клавиатуру у собственного сообщения действующего сотрудника.

    Вызывается при AppointmentAlreadyDecidedError: пока текущий сотрудник
    принимал решение, коллега уже обработал ту же заявку. Метка и текст исхода
    берутся из самого исключения (уже вычислены сервисом при попытке действия),
    чтобы не повторять запрос к БД.
    """
    decided_by_label = error.decided_by_label or "Другой сотрудник"
    outcome_text = error.outcome_text or "решение принято"

    await notification_service.invalidate_stale_decision_message(
        chat_id, message_id, decided_by_label, outcome_text,
    )
