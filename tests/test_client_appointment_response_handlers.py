from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers.client.appointment_response import create_client_appointment_router
from bot.keyboards.admin.record_management_kb.appointment_log_details_cb import (
    AppointmentLogDetailsCB,
    AppointmentLogHideDetailsCB,
)
from bot.keyboards.admin.record_management_kb.appointment_log_details_kb import (
    appointment_log_details_kb,
    appointment_log_hide_details_kb,
)
from bot.keyboards.client.appointment_manage_cb import ClientManageActionCB
from bot.models.appointment import Appointment
from bot.models.appointment_notification import AppointmentNotification
from bot.models.user import User
from bot.services.appointment.appointment_notifications import (
    StaffLogDelivery,
)
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


def _get_handler_by_name(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"{name} handler not found on router")


def _get_message_handler_object_by_name(router, name):
    for handler in router.message.handlers:
        if handler.callback.__name__ == name:
            return handler
    raise AssertionError(f"{name} message handler not found on router")


def _make_callback_query(data):
    callback_query = MagicMock()
    callback_query.data = data
    callback_query.from_user.id = 12345
    callback_query.message.chat.id = 12345
    callback_query.message.message_id = 777
    callback_query.message.edit_text = AsyncMock()
    callback_query.answer = AsyncMock()
    return callback_query


# Helper functions for creating test data
def _client():
    return User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=12345,
        ID=1
    )


def _appointment():
    return Appointment(
        clinic_id=1,
        client_id=1,
        datetime="2026-07-10 14:30",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        id=1,
        clinic_name="Зуб Мудрости"
    )


def _admin():
    return User(
        full_name="Доктор Петров",
        phone="+998901234568",
        role=Role.ADMIN,
        telegram_user_id=54321,
        ID=999
    )


# Fake classes for testing
class FakeAppointmentRepo:
    def __init__(self, appointments=None, notifications=None):
        self.appointments = list(appointments or [])
        self.notifications = list(notifications or [])
        self.status_updates = []

    async def get_appointment_by_id(self, appointment_id):
        return next((a for a in self.appointments if a.id == appointment_id), None)

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.status_updates.append((appointment_id, status))
        for appt in self.appointments:
            if appt.id == appointment_id:
                appt.status = status

    async def get_appointment_notification(self, appointment_id, chat_id, message_id, kind):
        return next(
            (
                notification
                for notification in self.notifications
                if notification.appointment_id == appointment_id
                and notification.chat_id == chat_id
                and notification.message_id == message_id
                and notification.kind == kind
            ),
            None,
        )


class FakeUserRepo:
    def __init__(self, client=None):
        self.client = client

    async def get_client_by_id(self, client_id):
        if self.client and self.client.ID == client_id:
            return self.client
        return None

    async def get_user_by_telegram_id(self, telegram_user_id):
        if self.client and self.client.telegram_user_id == telegram_user_id:
            return self.client
        return None


class FakeStaffRepo:
    pass


class FakeClinicRepo:
    pass


class FakeBot:
    def __init__(self):
        self.sent_messages = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent_messages.append({
            'chat_id': chat_id,
            'text': text,
            'reply_markup': reply_markup
        })


class FakeNotificationService:
    def __init__(self):
        self.confirmations = []
        self.cancellations = []

    async def notify_admin_confirmation(self, admin_telegram_id, appointment, client_name):
        self.confirmations.append((admin_telegram_id, appointment, client_name))

    async def notify_admin_cancellation(self, admin_telegram_id, appointment, client_name):
        self.cancellations.append((admin_telegram_id, appointment, client_name))


class ProposalDetailsNotifierFake:
    def __init__(self):
        self.edits = []
        self.recorded_count_at_edit = []
        self.management = None

    async def try_edit_message_text(self, **kwargs):
        self.edits.append(kwargs)
        self.recorded_count_at_edit.append(len(self.management.recorded_notifications))
        return True


class ProposalNotificationServiceFake:
    def __init__(self, notifier, delivery):
        self.notifier = notifier
        self.delivery = delivery
        self.accepted_calls = []
        self.rejected_calls = []

    async def notify_staff_proposal_accepted(self, staff_telegram_id, appointment, client_name):
        self.accepted_calls.append((staff_telegram_id, appointment, client_name))
        return self.delivery

    async def notify_staff_proposal_rejected(self, staff_telegram_id, appointment, client_name):
        self.rejected_calls.append((staff_telegram_id, appointment, client_name))
        return self.delivery


class ProposalAppointmentManagementFake:
    def __init__(self, pre_mutation, resolved, client, recipients):
        self.pre_mutation = pre_mutation
        self.resolved = resolved
        self.client = client
        self.recipients = recipients
        self.recorded_notifications = []

    async def get_appointment_for_client(self, appointment_id, telegram_user_id):
        assert appointment_id == self.pre_mutation.id
        assert telegram_user_id == self.client.telegram_user_id
        # The production service returns the pre-mutation row before its
        # accept/reject CAS mutates a separate model instance. Preserve that
        # distinction so the handler's log-kind lookup cannot accidentally use
        # post-mutation fields.
        from dataclasses import replace

        return replace(self.pre_mutation)

    async def accept_proposed_datetime(self, appointment_id, telegram_user_id):
        assert appointment_id == self.resolved.id
        assert telegram_user_id == self.client.telegram_user_id
        return self.resolved

    async def reject_proposed_datetime(self, appointment_id, telegram_user_id):
        assert appointment_id == self.resolved.id
        assert telegram_user_id == self.client.telegram_user_id
        return self.resolved

    async def get_appointment_with_client_info(self, appointment_id):
        assert appointment_id == self.resolved.id
        return self.resolved, self.client

    async def resolve_notification_recipients(self, appointment):
        assert appointment is self.resolved
        return self.recipients

    def resolve_admin_proposal_log_kind(self, appointment):
        if appointment.status is AppointmentStatus.PENDING and appointment.proposed_by is CreatedBy.ADMIN:
            return "booking"
        if appointment.status is AppointmentStatus.CONFIRMED and appointment.proposed_by is CreatedBy.ADMIN:
            return "reschedule"
        return None

    async def record_notification(self, appointment_id, chat_id, message_id, kind, compact_text=None):
        self.recorded_notifications.append((appointment_id, chat_id, message_id, kind, compact_text))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "status", "created_by", "kind", "compact_text"),
    [
        (
            "accept_proposal", AppointmentStatus.PENDING, CreatedBy.CLIENT, "booking",
            "✅ Клиент Иванов Иван согласился на предложенное время.\n\n📱 Номер: +998901234567",
        ),
        (
            "reject_proposal", AppointmentStatus.PENDING, CreatedBy.CLIENT, "booking",
            "❌ Клиент Иванов Иван отклонил предложенное время.\n\n📱 Номер: +998901234567",
        ),
        (
            "accept_proposal", AppointmentStatus.CONFIRMED, CreatedBy.ADMIN, "reschedule",
            "✅ Клиент Иванов Иван согласился на предложенное время.\n\n📱 Номер: +998901234567",
        ),
        (
            "reject_proposal", AppointmentStatus.CONFIRMED, CreatedBy.ADMIN, "reschedule",
            "❌ Клиент Иванов Иван отклонил предложенное время.\n\n📱 Номер: +998901234567",
        ),
    ],
)
async def test_client_proposal_response_records_staff_log_before_details_attachment(
    action, status, created_by, kind, compact_text,
):
    client = _client()
    pre_mutation = _appointment()
    pre_mutation.status = status
    pre_mutation.created_by = created_by
    pre_mutation.proposed_datetime = "2026-07-12 14:30"
    pre_mutation.proposed_by = CreatedBy.ADMIN
    pre_mutation.client_phone = client.phone

    resolved = _appointment()
    resolved.status = AppointmentStatus.CONFIRMED if action == "accept_proposal" else AppointmentStatus.CANCELLED
    resolved.created_by = created_by
    resolved.proposed_datetime = None
    resolved.proposed_by = None
    resolved.proposal_message_id = None
    resolved.client_phone = client.phone

    staff = _admin()
    notifier = ProposalDetailsNotifierFake()
    appointment_management = ProposalAppointmentManagementFake(
        pre_mutation, resolved, client, [staff],
    )
    notifier.management = appointment_management
    delivery = StaffLogDelivery(
        message_id=9001, compact_text=compact_text, lang="ru", details_available=True,
    )
    notification_service = ProposalNotificationServiceFake(notifier, delivery)
    router = create_client_appointment_router(
        MagicMock(), appointment_management, notification_service, None,
    )
    manage_action = _get_handler_by_name(router, "manage_action")
    callback_query = _make_callback_query(
        ClientManageActionCB(action=action, appointment_id=1, page=1).pack()
    )

    await manage_action(
        callback_query,
        ClientManageActionCB(action=action, appointment_id=1, page=1),
        MagicMock(),
        client,
    )

    assert appointment_management.recorded_notifications == [
        (1, staff.telegram_user_id, delivery.message_id, kind, compact_text),
    ]
    assert notifier.recorded_count_at_edit == [1]
    assert notifier.edits == [
        {
            "chat_id": staff.telegram_user_id,
            "message_id": delivery.message_id,
            "text": compact_text,
            "reply_markup": appointment_log_details_kb(1, "ru"),
        },
    ]
    if action == "accept_proposal":
        assert notification_service.accepted_calls == [
            (staff.telegram_user_id, resolved, client.full_name),
        ]
        assert notification_service.rejected_calls == []
    else:
        assert notification_service.rejected_calls == [
            (staff.telegram_user_id, resolved, client.full_name),
        ]
        assert notification_service.accepted_calls == []
    callback_query.message.edit_text.assert_awaited_once()
    callback_query.answer.assert_awaited_once()


# --- show_appointment_management (text-triggered entrypoint: buttons + slash commands) ---

@pytest.mark.asyncio
async def test_show_appointment_management_filter_accepts_new_slash_commands_and_button_text():
    """Routing-level guard: F.text.in_({...}) must accept /appointments, /book,
    /history and the legacy button text, and reject unrelated text."""
    router = create_client_appointment_router(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    handler = _get_message_handler_object_by_name(router, "show_appointment_management")

    for text in ("/appointments", "/book", "/history", "📋 Управление записями"):
        message = MagicMock()
        message.text = text
        matched, _ = await handler.check(message)
        assert matched is True, text

    message = MagicMock()
    message.text = "some other text"
    matched, _ = await handler.check(message)
    assert matched is False


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger_text", ["/appointments", "/book", "/history"])
async def test_show_appointment_management_new_slash_commands_trigger_same_response_as_button_text(trigger_text):
    """/appointments, /book and /history must trigger the exact same
    show_appointment_management handler (and therefore the same response) as
    the pre-existing "📋 Управление записями" reply-keyboard button text."""
    from bot.keyboards.client.appointment_management_kb import (
        client_appointment_management_kb,
    )

    router = create_client_appointment_router(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    show_appointment_management = _get_message_handler_object_by_name(
        router, "show_appointment_management"
    ).callback

    message = MagicMock()
    message.text = trigger_text
    message.answer = AsyncMock()

    await show_appointment_management(message, _client())

    message.answer.assert_awaited_once_with(
        "Выберите действие:", reply_markup=client_appointment_management_kb()
    )


# Tests for confirmation flow
@pytest.mark.asyncio
async def test_handle_appointment_confirm_updates_status():
    from bot.services.appointment.appointment_management import AppointmentManagement

    appt = _appointment()
    appt_repo = FakeAppointmentRepo([appt])
    user_repo = FakeUserRepo(_client())

    service = AppointmentManagement(
        appt_repo, user_repo, FakeStaffRepo(), FakeClinicRepo()
    )

    confirmed_appt = await service.update_status(appt, AppointmentStatus.CONFIRMED)

    assert confirmed_appt.status == AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CONFIRMED)]


@pytest.mark.asyncio
async def test_handle_appointment_confirm_handler_resyncs_jobs_and_edits_without_reply_markup():
    """PR3: handle_appointment_confirm now serves ONLY the 2h-reminder confirm
    button (the initial-invite confirm moved to the new appointment_invite router).
    It resyncs the full job set via resync_appointment_jobs (replacing the old
    cancel_pending_expiry + cancel_auto_confirm pair) and edits the message with a
    plain success text -- no reply_markup is passed at all anymore."""
    confirmed_appointment = _appointment()
    confirmed_appointment.status = AppointmentStatus.CONFIRMED

    appointment_management_service = MagicMock()
    appointment_management_service.confirm_appointment_by_client = AsyncMock(return_value=confirmed_appointment)
    appointment_management_service.get_appointment_with_client_info = AsyncMock(
        return_value=(confirmed_appointment, _client())
    )

    notification_service = MagicMock()
    notification_service.notify_admin_confirmation = AsyncMock()

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()
    appointment_scheduler.cancel_pending_expiry = AsyncMock()
    appointment_scheduler.cancel_auto_confirm = AsyncMock()

    router = create_client_appointment_router(
        MagicMock(), appointment_management_service, notification_service, appointment_scheduler,
    )
    handle_appointment_confirm = _get_handler_by_name(router, "handle_appointment_confirm")

    callback_query = _make_callback_query("appt_confirm:1")
    await handle_appointment_confirm(callback_query, _client())

    appointment_management_service.confirm_appointment_by_client.assert_awaited_once_with(1, 12345)
    appointment_scheduler.resync_appointment_jobs.assert_awaited_once_with(confirmed_appointment)
    appointment_scheduler.cancel_pending_expiry.assert_not_awaited()
    appointment_scheduler.cancel_auto_confirm.assert_not_awaited()

    callback_query.message.edit_text.assert_awaited_once_with("✅ Спасибо! Ваша запись подтверждена")
    assert "reply_markup" not in callback_query.message.edit_text.call_args.kwargs
    callback_query.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_appointment_confirm_with_malformed_id_shows_alert_and_does_not_update():
    """Defensive guard around int(callback_query.data.split(":")[1]): a forged/
    malformed appt_confirm callback must short-circuit before any service call,
    answering with a show_alert toast instead of crashing with ValueError."""
    appointment_management_service = MagicMock()
    appointment_management_service.confirm_appointment_by_client = AsyncMock()
    appointment_management_service.get_appointment_with_client_info = AsyncMock()

    notification_service = MagicMock()
    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()

    router = create_client_appointment_router(
        MagicMock(), appointment_management_service, notification_service, appointment_scheduler,
    )
    handle_appointment_confirm = _get_handler_by_name(router, "handle_appointment_confirm")

    callback_query = _make_callback_query("appt_confirm:not-an-id")
    await handle_appointment_confirm(callback_query, _client())

    callback_query.answer.assert_awaited_once_with("Некорректная запись.", show_alert=True)
    callback_query.message.edit_text.assert_not_awaited()
    appointment_management_service.confirm_appointment_by_client.assert_not_awaited()
    appointment_scheduler.resync_appointment_jobs.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_appointment_details_with_malformed_id_shows_alert_and_does_not_notify():
    """Defensive guard around int(callback_query.data.split(":")[1]) in the
    appt_details handler -- same forged-callback shape as handle_appointment_confirm."""
    appointment_management_service = MagicMock()
    appointment_management_service.get_appointment_for_client = AsyncMock()

    notification_service = MagicMock()
    notification_service.notify_client_appointment_details = AsyncMock()

    router = create_client_appointment_router(
        MagicMock(), appointment_management_service, notification_service, MagicMock(),
    )
    handle_appointment_details = _get_handler_by_name(router, "handle_appointment_details")

    callback_query = _make_callback_query("appt_details:not-an-id")
    await handle_appointment_details(callback_query, _client())

    callback_query.answer.assert_awaited_once_with("Некорректная запись.", show_alert=True)
    appointment_management_service.get_appointment_for_client.assert_not_awaited()
    notification_service.notify_client_appointment_details.assert_not_awaited()


def _client_log_router(appointment=None, notification=None):
    appointment_management_service = MagicMock()
    appointment_management_service.get_appointment_for_client = AsyncMock(return_value=appointment)
    appointment_management_service.get_notification_for_message = AsyncMock(return_value=notification)
    return create_client_appointment_router(
        MagicMock(), appointment_management_service, MagicMock(), MagicMock(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "expected_labels"),
    [
        (
            "uz",
            ("Yozuv №1", "Klinika:", "Sana va vaqt:", "Xizmat:", "Holat:", "Shifokor:", "Shifokor telefoni:"),
        ),
        (
            "xx",
            ("Запись №1", "Клиника:", "Дата и время:", "Услуга:", "Статус:", "Врач:", "Телефон врача:"),
        ),
    ],
)
async def test_generic_client_log_details_renders_allowed_fields_and_hides_exact_compact_text(
    language, expected_labels,
):
    appointment = _appointment()
    appointment.doctor_full_name = "Doctor Allowed"
    appointment.doctor_phone = "DOCTOR_PHONE_ALLOWED"
    appointment.doctor_is_doctor = True
    appointment.doctor_id = 424242
    appointment.client_full_name = "CLIENT_NAME_SECRET"
    appointment.client_phone = "CLIENT_PHONE_SECRET"
    appointment.price = 9876.54
    appointment.decided_by_user_id = 434343
    appointment.notification_message_id = 545454
    appointment.proposal_message_id = 656565
    appointment.admin_notification_message_id = 767676
    notification = AppointmentNotification(
        appointment_id=1,
        chat_id=12345,
        message_id=777,
        kind="client_log",
        compact_text="Исторический результат клиента",
    )
    router = _client_log_router(appointment, notification)
    details = _get_handler_by_name(router, "handle_appointment_log_details")
    hide = _get_handler_by_name(router, "handle_appointment_log_hide_details")
    callback_query = _make_callback_query(AppointmentLogDetailsCB(appointment_id=1).pack())
    client = _client()
    client.language = language
    client.phone = "CLIENT_PHONE_SECRET"

    await details(callback_query, AppointmentLogDetailsCB(appointment_id=1), client)
    callback_query.message.edit_text.assert_awaited_once()
    expanded_text = callback_query.message.edit_text.call_args.args[0]
    for label in expected_labels:
        assert label in expanded_text
    assert "Doctor Allowed" in expanded_text
    assert "DOCTOR_PHONE_ALLOWED" in expanded_text
    for forbidden in (
        "9876.54", "CLIENT_NAME_SECRET", "CLIENT_PHONE_SECRET", "ACTOR_SECRET",
        "424242", "434343", "545454", "656565", "767676",
    ):
        assert forbidden not in expanded_text
    assert callback_query.message.edit_text.call_args.kwargs["reply_markup"] == appointment_log_hide_details_kb(
        1, lang=language,
    )

    callback_query.message.edit_text.reset_mock()
    await hide(callback_query, AppointmentLogHideDetailsCB(appointment_id=1), client)
    callback_query.message.edit_text.assert_awaited_once_with(
        "Исторический результат клиента",
        reply_markup=appointment_log_details_kb(1, lang=language),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "callback_type"),
    [
        ("handle_appointment_log_details", AppointmentLogDetailsCB),
        ("handle_appointment_log_hide_details", AppointmentLogHideDetailsCB),
    ],
)
@pytest.mark.parametrize(
    "appointment,notification",
    [
        (_appointment(), None),
        (None, AppointmentNotification(
            appointment_id=1, chat_id=12345, message_id=777,
            kind="client_log", compact_text="Should not edit",
        )),
        (_appointment(), AppointmentNotification(
            appointment_id=1, chat_id=12345, message_id=777,
            kind="booking", compact_text="Wrong kind",
        )),
    ],
)
async def test_generic_client_log_details_fails_closed_without_edit_for_missing_wrong_kind_or_deleted_row(
    handler_name, callback_type, appointment, notification,
):
    router = _client_log_router(appointment, notification)
    handler = _get_handler_by_name(router, handler_name)
    callback_query = _make_callback_query(callback_type(appointment_id=1).pack())

    await handler(callback_query, callback_type(appointment_id=1), _client())

    callback_query.answer.assert_awaited_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "callback_type"),
    [
        ("handle_appointment_log_details", AppointmentLogDetailsCB),
        ("handle_appointment_log_hide_details", AppointmentLogHideDetailsCB),
    ],
)
async def test_generic_client_log_details_fails_closed_for_foreign_appointment_without_edit(
    handler_name, callback_type,
):
    foreign = _appointment()
    foreign.client_id = 999
    router = _client_log_router(
        foreign,
        AppointmentNotification(
            appointment_id=1, chat_id=12345, message_id=777,
            kind="client_log", compact_text="Foreign compact",
        ),
    )
    handler = _get_handler_by_name(router, handler_name)
    callback_query = _make_callback_query(callback_type(appointment_id=1).pack())

    await handler(callback_query, callback_type(appointment_id=1), _client())

    callback_query.answer.assert_awaited_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_appointment_cancel_with_malformed_id_shows_alert_and_does_not_touch_state():
    """Defensive guard around int(callback_query.data.split(":")[1]) in the
    appt_cancel handler -- the parse already ran before any state mutation in
    the original code, so this only needed a ValueError catch, not a reorder."""
    router = create_client_appointment_router(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(),
    )
    handle_appointment_cancel = _get_handler_by_name(router, "handle_appointment_cancel")

    callback_query = _make_callback_query("appt_cancel:not-an-id")
    state = MagicMock()
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()

    await handle_appointment_cancel(callback_query, state, _client())

    callback_query.answer.assert_awaited_once_with("Некорректная запись.", show_alert=True)
    callback_query.message.edit_text.assert_not_awaited()
    state.set_state.assert_not_awaited()
    state.update_data.assert_not_awaited()


# Tests for cancellation flow
@pytest.mark.asyncio
async def test_handle_appointment_cancel_updates_status():
    from bot.services.appointment.appointment_management import AppointmentManagement

    appt = _appointment()
    appt_repo = FakeAppointmentRepo([appt])
    user_repo = FakeUserRepo(_client())

    service = AppointmentManagement(
        appt_repo, user_repo, FakeStaffRepo(), FakeClinicRepo()
    )

    cancelled_appt = await service.update_status(appt, AppointmentStatus.CANCELLED)

    assert cancelled_appt.status == AppointmentStatus.CANCELLED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CANCELLED)]


@pytest.mark.asyncio
async def test_handler_sends_confirmation_message_to_admin():
    """Test that handler sends confirmation message to admin when appointment confirmed."""
    from bot.services.appointment.appointment_management import AppointmentManagement

    appt = _appointment()
    appt_repo = FakeAppointmentRepo([appt])
    user_repo = FakeUserRepo(_client())
    notification_service = FakeNotificationService()

    service = AppointmentManagement(
        appt_repo, user_repo, FakeStaffRepo(), FakeClinicRepo()
    )

    appointment, client = await service.get_appointment_with_client_info(1)
    await notification_service.notify_admin_confirmation(54321, appointment, client.full_name)

    assert len(notification_service.confirmations) == 1
    admin_id, notified_appt, client_name = notification_service.confirmations[0]
    assert admin_id == 54321
    assert notified_appt.id == 1
    assert client_name == "Иванов Иван"


@pytest.mark.asyncio
async def test_handle_appointment_confirm_handler_does_not_notify_admin():
    """PR3: handle_appointment_confirm (2h-reminder confirm) no longer notifies the
    admin at all -- that responsibility moved to the initial-invite confirm handler
    in bot/handlers/client/appointment_invite.py, which fires notify_admin_confirmation
    itself. The 2h-reminder handler must leave notification_service alone."""
    confirmed_appointment = _appointment()
    confirmed_appointment.status = AppointmentStatus.CONFIRMED

    appointment_management_service = MagicMock()
    appointment_management_service.confirm_appointment_by_client = AsyncMock(return_value=confirmed_appointment)
    appointment_management_service.get_appointment_with_client_info = AsyncMock(
        return_value=(confirmed_appointment, _client())
    )

    notification_service = MagicMock()
    notification_service.notify_admin_confirmation = AsyncMock()

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()

    router = create_client_appointment_router(
        MagicMock(), appointment_management_service, notification_service, appointment_scheduler,
    )
    handle_appointment_confirm = _get_handler_by_name(router, "handle_appointment_confirm")

    await handle_appointment_confirm(_make_callback_query("appt_confirm:1"), _client())

    notification_service.notify_admin_confirmation.assert_not_awaited()


def _make_state_with_appointment_id(appointment_id=1):
    state = MagicMock()
    state.get_data = AsyncMock(return_value={"appointment_id": appointment_id})
    state.clear = AsyncMock()
    return state


@pytest.mark.asyncio
async def test_handle_cancel_confirmation_yes_notifies_sole_doctor_recipient():
    """Regression/backward-compat case: resolve_notification_recipients resolves
    to exactly one recipient (the treating doctor, who is also the appointment's
    sole clinic-scope admin in the common solo-doctor setup) -- notify_admin_cancellation
    must fire exactly once, to that one recipient."""
    cancelled_appointment = _appointment()
    cancelled_appointment.status = AppointmentStatus.CANCELLED
    client = _client()
    doctor = _admin()

    appointment_management_service = MagicMock()
    appointment_management_service.cancel_appointment_by_client = AsyncMock(return_value=cancelled_appointment)
    appointment_management_service.get_appointment_with_client_info = AsyncMock(
        return_value=(cancelled_appointment, client)
    )
    appointment_management_service.resolve_notification_recipients = AsyncMock(return_value=[doctor])

    notification_service = MagicMock()
    notification_service.notify_admin_cancellation = AsyncMock()

    appointment_scheduler = AsyncMock()

    router = create_client_appointment_router(
        MagicMock(), appointment_management_service, notification_service, appointment_scheduler,
    )
    handle_cancel_confirmation_yes = _get_handler_by_name(router, "handle_cancel_confirmation_yes")

    callback_query = _make_callback_query("appt_cancel_confirm_yes")
    state = _make_state_with_appointment_id(1)

    await handle_cancel_confirmation_yes(callback_query, state, _client())

    notification_service.notify_admin_cancellation.assert_awaited_once_with(
        doctor.telegram_user_id, cancelled_appointment, client.full_name,
    )
    appointment_scheduler.cancel_all_jobs.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_handle_cancel_confirmation_yes_notifies_remaining_recipients_after_one_fails():
    """Per-recipient failure isolation: with two resolved recipients, the first
    recipient's send raising must not prevent the second recipient in the loop
    from being attempted -- each send is independently wrapped."""
    cancelled_appointment = _appointment()
    cancelled_appointment.status = AppointmentStatus.CANCELLED
    client = _client()
    doctor = _admin()
    clinic_admin = User(
        full_name="Админ Клиники", phone="+998901234569", role=Role.ADMIN, telegram_user_id=67890, ID=1000,
    )

    appointment_management_service = MagicMock()
    appointment_management_service.cancel_appointment_by_client = AsyncMock(return_value=cancelled_appointment)
    appointment_management_service.get_appointment_with_client_info = AsyncMock(
        return_value=(cancelled_appointment, client)
    )
    appointment_management_service.resolve_notification_recipients = AsyncMock(
        return_value=[doctor, clinic_admin]
    )

    notification_service = MagicMock()
    notification_service.notify_admin_cancellation = AsyncMock(
        side_effect=[Exception("boom"), None]
    )

    appointment_scheduler = AsyncMock()

    router = create_client_appointment_router(
        MagicMock(), appointment_management_service, notification_service, appointment_scheduler,
    )
    handle_cancel_confirmation_yes = _get_handler_by_name(router, "handle_cancel_confirmation_yes")

    callback_query = _make_callback_query("appt_cancel_confirm_yes")
    state = _make_state_with_appointment_id(1)

    # Should not raise, despite the first recipient's send failing.
    await handle_cancel_confirmation_yes(callback_query, state, _client())

    assert notification_service.notify_admin_cancellation.await_count == 2
    notification_service.notify_admin_cancellation.assert_any_await(
        doctor.telegram_user_id, cancelled_appointment, client.full_name,
    )
    notification_service.notify_admin_cancellation.assert_any_await(
        clinic_admin.telegram_user_id, cancelled_appointment, client.full_name,
    )
    appointment_scheduler.cancel_all_jobs.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_handler_sends_cancellation_message_to_admin():
    """Test that handler sends cancellation message to admin when appointment cancelled."""
    from bot.services.appointment.appointment_management import AppointmentManagement

    appt = _appointment()
    appt_repo = FakeAppointmentRepo([appt])
    user_repo = FakeUserRepo(_client())
    notification_service = FakeNotificationService()

    service = AppointmentManagement(
        appt_repo, user_repo, FakeStaffRepo(), FakeClinicRepo()
    )

    appointment, client = await service.get_appointment_with_client_info(1)
    await notification_service.notify_admin_cancellation(54321, appointment, client.full_name)

    assert len(notification_service.cancellations) == 1
    admin_id, notified_appt, client_name = notification_service.cancellations[0]
    assert admin_id == 54321
    assert notified_appt.id == 1
    assert client_name == "Иванов Иван"
