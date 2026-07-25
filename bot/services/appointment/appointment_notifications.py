import logging
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ReplyParameters

from bot.exceptions.appointment_exceptions import NotificationDeliveryError
from bot.keyboards.admin.record_management_kb.booking_request_kb import booking_request_kb
from bot.keyboards.admin.record_management_kb.completion_followup_kb import completion_followup_kb
from bot.keyboards.admin.record_management_kb.reschedule_request_kb import reschedule_request_kb
from bot.keyboards.client.appointment_response_kb import (
    appointment_invite_kb,
    appointment_reminder_details_kb,
    appointment_reminder_with_buttons_kb,
    reschedule_proposal_kb,
)
from bot.models.appointment import Appointment
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.user_repository import UserRepository
from bot.services.utils.date_parser import (
    RESCHEDULE_NEGOTIATION_NOTE,
    build_reschedule_proposal_line,
    format_datetime_for_display,
)
from bot.utils.appointment_enums import APPOINTMENT_STATUS_LABELS, AppointmentStatus, CreatedBy

logger = logging.getLogger(__name__)

REMINDER_TEXT = "Напоминаем вам о записи."


def _format_datetime_value(value: str) -> str:
    try:
        return format_datetime_for_display(datetime.fromisoformat(value))
    except ValueError:
        return value


class AppointmentNotificationService:
    def __init__(
        self,
        bot: Bot,
        user_repo: UserRepository,
        appointment_repo: AppointmentRepository
    ):
        self.bot = bot
        self.user_repo = user_repo
        self.appointment_repo = appointment_repo

    async def notify_client_appointment_with_buttons(
        self, appointment: Appointment, use_invite_kb: bool = True
    ) -> int | None:
        """Send full appointment notification to client WITH confirmation buttons (on creation).

        use_invite_kb controls which keyboard is attached:
        - True (default): the record is still an unresolved admin-created invite
          (PENDING+ADMIN) — the client sees Confirm / Propose different time / Cancel.
        - False: the record is already CONFIRMED (e.g. the clinic just approved the
          client's own self-booking request) — no decision is pending, so no
          negotiation buttons are shown.

        Returns the sent message's message_id (to be persisted so later reminders can reply
        to it), or None if the client was not found or has no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return None

        admin = await self.user_repo.get_user_by_id(appointment.doctor_id) if appointment.doctor_id else None
        message_text = self._build_appointment_message(appointment, admin)

        reply_markup = (
            appointment_invite_kb(appointment.id) if use_invite_kb
            else appointment_reminder_details_kb(appointment.id)
        )

        sent_message = await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_markup=reply_markup,
        )

        return sent_message.message_id

    async def notify_client_reminder_without_buttons(self, appointment: Appointment) -> bool:
        """Send short appointment reminder to client as a reply, WITHOUT buttons (24h reminder).

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=REMINDER_TEXT,
            reply_markup=appointment_reminder_details_kb(appointment.id),
            reply_parameters=self._reply_parameters(appointment),
        )

        return True

    async def notify_client_reminder_with_buttons(self, appointment: Appointment) -> bool:
        """Send short appointment reminder to client as a reply, WITH confirmation buttons (2h reminder).

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=REMINDER_TEXT,
            reply_markup=appointment_reminder_with_buttons_kb(appointment.id),
            reply_parameters=self._reply_parameters(appointment),
        )

        return True

    async def notify_client_appointment_details(self, appointment: Appointment) -> bool:
        """Rebuild the original confirmation message into a full appointment details card.

        Edits the original notification_message_id in place; falls back to sending a
        new message if that original message is gone/inaccessible.

        Returns True if the card was shown (edited or newly sent), False if the
        client was not found or has no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        admin = await self.user_repo.get_user_by_id(appointment.doctor_id) if appointment.doctor_id else None
        message_text = self._build_appointment_message(appointment, admin)

        if appointment.status == AppointmentStatus.PENDING:
            reply_markup = appointment_invite_kb(appointment.id)
        else:
            reply_markup = appointment_reminder_details_kb(appointment.id)

        if appointment.notification_message_id is not None:
            try:
                await self.bot.edit_message_text(
                    chat_id=client.telegram_user_id,
                    message_id=appointment.notification_message_id,
                    text=message_text,
                    reply_markup=reply_markup,
                )
                return True
            except TelegramBadRequest as e:
                if "message is not modified" in str(e):
                    return True

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_markup=reply_markup,
        )
        return True

    async def notify_client_appointment_cancelled_by_admin(self, appointment: Appointment) -> bool:
        """Notify client that their appointment was cancelled by an administrator.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text="❌ Ваша запись отменена администратором.",
            reply_parameters=self._reply_parameters(appointment),
        )

        return True

    async def notify_client_booking_request_rejected(self, appointment: Appointment) -> bool:
        """Notify client that their self-booking request was declined by the clinic.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text="❌ Клиника отклонила вашу заявку на запись.",
        )

        return True

    # async def notify_client_appointment_changed(self, appointment: Appointment) -> bool:
    #     """Notify client that details of their appointment (datetime or purpose) were changed.
    #
    #     Returns True if message sent, False if user not found or no telegram_id.
    #     """
    #     client = await self.user_repo.get_client_by_id(appointment.client_id)
    #
    #     if client is None or client.telegram_user_id is None:
    #         return False
    #
    #     message_text = (
    #         "✏️ Детали вашей записи изменены администратором\n\n"
    #         f"Дата и время: {appointment.datetime}\n"
    #         f"Услуга: {appointment.purpose}"
    #     )
    #
    #     await self.bot.send_message(
    #         chat_id=client.telegram_user_id,
    #         text=message_text,
    #         reply_parameters=self._reply_parameters(appointment),
    #     )
    #
    #     return True

    def _reply_parameters(self, appointment: Appointment) -> ReplyParameters | None:
        if appointment.notification_message_id is None:
            return None

        return ReplyParameters(
            message_id=appointment.notification_message_id,
            allow_sending_without_reply=True,
        )

    def _admin_reply_parameters(self, appointment: Appointment) -> ReplyParameters | None:
        if appointment.admin_notification_message_id is None:
            return None

        return ReplyParameters(
            message_id=appointment.admin_notification_message_id,
            allow_sending_without_reply=True,
        )

    async def notify_admin_upcoming_appointment(
        self,
        admin_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> None:
        """Send reminder to admin about upcoming appointment WITHOUT buttons.

        Raises NotificationDeliveryError if the message could not be sent.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)
        client_phone = client.phone if client else "—"

        message_text = (
            f"📌 Предстоящая запись:\n\n"
            f"👤 Клиент: {client_name}\n"
            f"📱 Номер: {client_phone}\n"
            f"📅 Дата и время: {appointment.datetime}\n"
            f"🏥 Услуга: {appointment.purpose}"
        )

        try:
            await self.bot.send_message(
                chat_id=admin_telegram_id,
                text=message_text,
            )
        except Exception as e:
            raise NotificationDeliveryError(
                f"Не удалось отправить напоминание администратору {admin_telegram_id}: {e}"
            ) from e

    async def notify_admin_cancellation(
        self,
        admin_telegram_id: int,
        appointment: Appointment,
        client_name: str
    ) -> None:
        """Send cancellation notification to admin."""
        await self.bot.send_message(
            chat_id=admin_telegram_id,
            text=f"Клиент {client_name} отменил запись.",
            reply_parameters=self._admin_reply_parameters(appointment),
        )

    async def notify_admin_client_changed_time(
        self,
        admin_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> None:
        """Notify admin that the client changed the time of their own pending self-booking request."""
        await self.bot.send_message(
            chat_id=admin_telegram_id,
            text=(
                f"🕐 Клиент {client_name} изменил время заявки.\n"
                f"📅 Новое время: {_format_datetime_value(appointment.datetime)}"
            ),
            reply_parameters=self._admin_reply_parameters(appointment),
        )

    async def notify_admin_confirmation(
        self,
        admin_telegram_id: int,
        appointment: Appointment,
        client_name: str
    ) -> None:
        """Send confirmation notification to admin."""
        await self.bot.send_message(
            chat_id=admin_telegram_id,
            text=f"Клиент {client_name} подтвердил запись.",
            reply_parameters=self._admin_reply_parameters(appointment),
        )

    async def notify_admin_completion(self, admin_telegram_id: int, appointment: Appointment) -> int | None:
        """Ask admin whether to make post-appointment corrections before finalizing the status.

        Returns the sent message's message_id on success.
        """
        sent_message = await self.bot.send_message(
            chat_id=admin_telegram_id,
            text="Приём отмечен как завершённый. Открыть запись для правок (статус/услуга/цена)?",
            reply_markup=completion_followup_kb(appointment.id),
            reply_parameters=self._admin_reply_parameters(appointment),
        )

        return sent_message.message_id

    async def notify_staff_new_booking_request(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> int | None:
        """Notify the chosen staff member about a new client self-booking request.

        Sends Confirm / Propose-different-time / Reject action buttons.
        Returns the sent message's message_id on success.
        Raises NotificationDeliveryError if the message could not be sent.
        """
        message_text = (
            f"🆕 Новая заявка на запись\n\n"
            f"👤 Клиент: {client_name}\n"
            f"📅 Дата и время: {appointment.datetime}\n"
            f"📝 Жалоба: {appointment.purpose}"
        )

        try:
            sent_message = await self.bot.send_message(
                chat_id=staff_telegram_id,
                text=message_text,
                reply_markup=booking_request_kb(appointment.id),
            )
        except Exception as e:
            raise NotificationDeliveryError(
                f"Не удалось отправить уведомление специалисту {staff_telegram_id}: {e}"
            ) from e

        return sent_message.message_id

    async def notify_client_auto_confirmed(self, appointment: Appointment) -> bool:
        """[LEGACY] Notify client that their appointment was auto-confirmed.

        Previously called 2 hours before the appointment when the admin did not
        manually confirm a PENDING appointment. This notification is now only sent
        for legacy jobs persisted in the job store before the auto-confirm mechanism
        was retired. New appointments no longer use auto-confirm.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text="✅ Ваша запись подтверждена (автоматически за 2 часа до приема).",
            reply_parameters=self._reply_parameters(appointment),
        )

        return True

    async def notify_client_pending_request_expired(self, appointment: Appointment) -> bool:
        """Notify client that their unanswered PENDING request has expired.

        Covers three cases: a client self-booking request the clinic never answered;
        an admin-created invite the client never answered at all; and an admin-created
        appointment where the client proposed their own time and the clinic never
        answered that counter-proposal. When a proposal was outstanding, the wording
        stays neutral about which side missed the deadline.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        if appointment.proposed_datetime is not None:
            text = "⌛ Предложение по времени записи осталось без ответа, заявка на запись истекла."
        elif appointment.created_by == CreatedBy.ADMIN:
            text = "⌛ Вы не ответили на приглашение клиники на запись, заявка истекла."
        else:
            text = "⌛ Ваша заявка на запись истекла без ответа клиники."

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=text,
        )

        return True

    async def notify_client_reschedule_proposed(self, appointment: Appointment) -> int | None:
        """Notify client that the clinic proposed a different time for their request.

        Returns the sent message's message_id (to be persisted so the proposal message
        can later be closed), or None if the client was not found or has no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return None

        message_text = (
            "🔁 Клиника предложила другое время для вашей заявки\n\n"
            f"Предложенное время: {_format_datetime_value(appointment.proposed_datetime)}\n\n"
            "Согласны на новое время?"
        )

        sent_message = await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_markup=reschedule_proposal_kb(appointment.id),
            reply_parameters=self._reply_parameters(appointment),
        )

        return sent_message.message_id

    async def notify_client_appointment_reschedule_proposed(self, appointment: Appointment) -> int | None:
        """Notify client that the clinic proposed a different time for their confirmed appointment.

        Returns the sent message's message_id (to be persisted so the proposal message
        can later be closed), or None if the client was not found or has no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return None

        message_text = (
            "🔁 Клиника предлагает перенести вашу запись на другое время\n\n"
            f"Текущее время: {_format_datetime_value(appointment.datetime)}\n"
            f"Предложенное время: {_format_datetime_value(appointment.proposed_datetime)}\n\n"
            "Согласны на новое время?"
        )

        sent_message = await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_markup=reschedule_proposal_kb(appointment.id),
            reply_parameters=self._reply_parameters(appointment),
        )

        return sent_message.message_id

    async def notify_client_proposal_reminder(self, appointment: Appointment) -> bool:
        """Remind client that the clinic's proposed time is still awaiting a response.

        Sent partway through the proposal window, as a plain reply to the original
        proposal message (no buttons of its own — the client answers there).

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = (
            "⏰ Напоминаем: клиника предложила другое время для вашей заявки\n\n"
            f"Предложенное время: {_format_datetime_value(appointment.proposed_datetime)}\n\n"
            "Пожалуйста, ответьте на предыдущее сообщение с кнопками, "
            "иначе заявка скоро автоматически аннулируется."
        )

        reply_parameters = None
        if appointment.proposal_message_id is not None:
            reply_parameters = ReplyParameters(
                message_id=appointment.proposal_message_id,
                allow_sending_without_reply=True,
            )

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_parameters=reply_parameters,
        )

        return True

    async def notify_client_appointment_reschedule_reminder(self, appointment: Appointment) -> bool:
        """Remind client that the clinic's proposed reschedule for their confirmed
        appointment is still awaiting a response.

        Sent partway through the reschedule window, as a plain reply to the original
        proposal message (no buttons of its own — the client answers there).

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = (
            "⏰ Напоминаем: клиника предлагает перенести вашу запись на другое время\n\n"
            f"Текущее время: {_format_datetime_value(appointment.datetime)}\n"
            f"Предложенное время: {_format_datetime_value(appointment.proposed_datetime)}\n\n"
            "Пожалуйста, ответьте на предыдущее сообщение с кнопками, "
            "иначе предложение скоро автоматически аннулируется."
        )

        reply_parameters = None
        if appointment.proposal_message_id is not None:
            reply_parameters = ReplyParameters(
                message_id=appointment.proposal_message_id,
                allow_sending_without_reply=True,
            )

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_parameters=reply_parameters,
        )

        return True

    async def close_reschedule_proposal_message(
        self, chat_id: int, message_id: int, text: str = "Это предложение больше не актуально."
    ) -> None:
        """Edit a stale reschedule-proposal message so it no longer looks actionable."""
        await self.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)

    async def invalidate_stale_decision_message(
        self, chat_id: int, message_id: int, decided_by_label: str, outcome_text: str
    ) -> None:
        """Edit a stale staff notification once another recipient has already decided.

        Strips the inline keyboard and replaces the text so the message no longer
        looks actionable. Never raises — a failed edit (message deleted, bot blocked,
        "message is not modified") is logged and swallowed so it doesn't abort a loop
        of invalidation calls across multiple recipients.
        """
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"{decided_by_label} уже принял(а) решение: {outcome_text}.",
                reply_markup=None,
            )
        except TelegramBadRequest as e:
            logger.warning(
                f"Failed to invalidate stale decision message {message_id} in chat {chat_id}: {e}"
            )

    async def notify_staff_proposal_accepted(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> None:
        """Notify staff that the client accepted the proposed new time."""
        await self.bot.send_message(
            chat_id=staff_telegram_id,
            text=f"✅ Клиент {client_name} согласился на предложенное время.",
            reply_parameters=self._admin_reply_parameters(appointment),
        )

    async def notify_staff_proposal_rejected(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> None:
        """Notify staff that the client rejected the proposed new time."""
        await self.bot.send_message(
            chat_id=staff_telegram_id,
            text=f"❌ Клиент {client_name} отклонил предложенное время.",
            reply_parameters=self._admin_reply_parameters(appointment),
        )

    async def notify_admin_proposal_reminder(self, telegram_id: int, appointment: Appointment) -> None:
        """Remind the clinic that the client's proposed time is still awaiting a response.

        Status-neutral: reused for both an outstanding client counter-proposal on a
        PENDING admin-created invite, and a client-requested reschedule on a CONFIRMED
        appointment. Sent as a reply to the original admin notification message.
        """
        await self.bot.send_message(
            chat_id=telegram_id,
            text="⏰ Клиент предложил другое время, ответ ещё не получен.",
            reply_parameters=self._admin_reply_parameters(appointment),
        )

    async def notify_staff_reschedule_requested(
        self,
        staff_telegram_id: int,
        appointment: Appointment,
        client_name: str,
    ) -> int | None:
        """Notify staff that a client wants to reschedule a confirmed appointment.

        Sends Accept / Reject action buttons.
        Returns the sent message's message_id on success.
        Raises NotificationDeliveryError if the message could not be sent.
        """
        message_text = (
            f"🔁 Клиент просит перенести запись\n\n"
            f"👤 Клиент: {client_name}\n"
            f"📱 Номер: {appointment.client_phone or '—'}\n"
            f"📅 Текущее время: {_format_datetime_value(appointment.datetime)}\n"
            f"🆕 Предложенное время: {_format_datetime_value(appointment.proposed_datetime)}\n"
            f"📝 Услуга: {appointment.purpose}"
        )

        try:
            sent_message = await self.bot.send_message(
                chat_id=staff_telegram_id,
                text=message_text,
                reply_markup=reschedule_request_kb(appointment.id),
            )
        except Exception as e:
            raise NotificationDeliveryError(
                f"Не удалось отправить уведомление специалисту {staff_telegram_id}: {e}"
            ) from e

        return sent_message.message_id

    async def notify_client_reschedule_accepted(self, appointment: Appointment) -> bool:
        """Notify client that the clinic accepted their reschedule request.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = (
            "✅ Клиника приняла ваш перенос записи\n\n"
            f"Новое время: {_format_datetime_value(appointment.datetime)}"
        )

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_parameters=self._reply_parameters(appointment),
        )

        return True

    async def notify_client_reschedule_rejected(self, appointment: Appointment) -> bool:
        """Notify client that the clinic could not accommodate their reschedule request.

        The appointment is cancelled as a result — this is a terminal outcome,
        not a return to the original confirmed time.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = (
            "❌ Клиника не смогла подтвердить перенос записи, запись отменена\n\n"
            "Если запись всё ещё нужна, свяжитесь с клиникой или отправьте новую заявку."
        )

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_parameters=self._reply_parameters(appointment),
        )

        return True

    async def notify_client_reschedule_request_expired(self, appointment: Appointment) -> bool:
        """Notify client that a reschedule proposal on their appointment went unanswered in time.

        Used both when the client proposed a time and the clinic never answered, and
        when the clinic proposed a time and the client never answered — the wording
        stays neutral about which side missed the deadline. The original appointment
        remains CONFIRMED and unchanged.

        Returns True if message sent, False if user not found or no telegram_id.
        """
        client = await self.user_repo.get_client_by_id(appointment.client_id)

        if client is None or client.telegram_user_id is None:
            return False

        message_text = (
            "⌛ Предложение по времени записи истекло без ответа\n\n"
            f"Ваша запись остаётся в силе на прежнее время: {_format_datetime_value(appointment.datetime)}\n"
            "Актуальную информацию по записи смотрите в разделе «Мои записи»."
        )

        await self.bot.send_message(
            chat_id=client.telegram_user_id,
            text=message_text,
            reply_parameters=self._reply_parameters(appointment),
        )

        return True

    def _build_appointment_message(
        self,
        appointment: Appointment,
        admin: User | None = None,
    ) -> str:
        """Build appointment notification message for client."""
        admin_info = ""
        if admin:
            admin_info = f"👨‍⚕️ Администратор: {admin.full_name}\n📱 Номер: {admin.phone or '—'}\n\n"

        if appointment.status == AppointmentStatus.PENDING:
            last_line = "Пожалуйста, подтвердите вашу готовность посетить запись"
        else:
            last_line = f"Статус: {APPOINTMENT_STATUS_LABELS.get(appointment.status, appointment.status.value)}"

        message = (
            "Вам назначена запись на прием\n\n"
            f"{admin_info}"
            f"Дата и время: {appointment.datetime}\n"
            f"Услуга: {appointment.purpose}\n"
            f"Клиника: {appointment.clinic_name or 'Информация не доступна'}\n\n"
            f"{last_line}"
        )

        if appointment.status == AppointmentStatus.CONFIRMED and appointment.proposed_datetime is not None:
            proposal_line = build_reschedule_proposal_line(appointment, viewer=CreatedBy.CLIENT)
            message += f"\n\n{proposal_line}\n{RESCHEDULE_NEGOTIATION_NOTE}"

        return message
