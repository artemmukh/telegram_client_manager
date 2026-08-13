from bot.keyboards.admin.record_management_kb.appointment_log_details_kb import (
    appointment_log_details_kb,
)
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import StaffLogDelivery
from bot.services.utils.telegram_notifier import TelegramNotifier


async def record_staff_log_delivery(
    appt_mng: AppointmentManagement,
    notifier: TelegramNotifier,
    *,
    appointment_id: int,
    chat_id: int,
    kind: str,
    delivery: StaffLogDelivery,
) -> None:
    await appt_mng.record_notification(
        appointment_id,
        chat_id,
        delivery.message_id,
        kind=kind,
        compact_text=delivery.compact_text,
    )

    if delivery.details_available is True:
        await notifier.try_edit_message_text(
            chat_id=chat_id,
            message_id=delivery.message_id,
            text=delivery.compact_text,
            reply_markup=appointment_log_details_kb(appointment_id, delivery.lang),
        )
