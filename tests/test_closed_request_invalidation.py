"""Tests for closing staff request keyboards when a request dies without any
staff decision -- the client cancelled, or the request expired unanswered.

Both paths previously left the "Подтвердить/Отклонить" inline keyboard live in
every staff chat forever: pressing it could only ever produce an error popup,
because the service guards (_ensure_not_finalized / expire_*) had already moved
the appointment out of the actionable state. invalidate_sibling_notifications
does not cover them -- it names the staff member who decided, and here nobody did.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.client.appointment_response import create_client_appointment_router
from bot.keyboards.client.appointment_manage_cb import ClientManageActionCB
from bot.models.appointment import Appointment
from bot.models.appointment_notification import AppointmentNotification
from bot.models.user import User
from bot.services.appointment.appointment_jobs import (
    _PENDING_EXPIRED_OUTCOME,
    _close_staff_request_keyboards,
)
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role

CLIENT_TELEGRAM_ID = 4242
DOCTOR_CHAT_ID = 100
ADMIN_CHAT_ID = 200


def _client_user():
    return User(
        full_name="Ivanov Ivan", phone="+998901234567", role=Role.CLIENT,
        telegram_user_id=CLIENT_TELEGRAM_ID, ID=7, clinic_id=1, clinic_name="Zub Mudrosti",
        language="ru",
    )


def _appointment():
    return Appointment(
        clinic_id=1, client_id=7, doctor_id=5, datetime="2026-08-01 10:00", purpose="Konsultatsiya",
        created_by=CreatedBy.CLIENT, status=AppointmentStatus.CANCELLED, id=1,
    )


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


@pytest.mark.asyncio
async def test_close_staff_request_keyboards_invalidates_every_recorded_target():
    appt_mng = MagicMock()
    appt_mng.get_invalidation_targets = AsyncMock(side_effect=lambda appointment_id, kind, actor_chat_id: {
        "booking": [
            AppointmentNotification(appointment_id=1, chat_id=DOCTOR_CHAT_ID, message_id=11, kind="booking"),
            AppointmentNotification(appointment_id=1, chat_id=ADMIN_CHAT_ID, message_id=12, kind="booking"),
        ],
        "reschedule": [
            AppointmentNotification(appointment_id=1, chat_id=DOCTOR_CHAT_ID, message_id=13, kind="reschedule"),
        ],
    }[kind])
    notification_service = MagicMock()
    notification_service.invalidate_closed_request_message = AsyncMock()

    await _close_staff_request_keyboards(
        appt_mng, notification_service, 1, ("booking", "reschedule"), _PENDING_EXPIRED_OUTCOME,
    )

    # actor_chat_id=0: nobody decided, so no chat is excluded from invalidation.
    for call in appt_mng.get_invalidation_targets.await_args_list:
        assert call.kwargs["actor_chat_id"] == 0

    assert notification_service.invalidate_closed_request_message.await_count == 3
    assert [
        (call.args[0], call.args[1])
        for call in notification_service.invalidate_closed_request_message.await_args_list
    ] == [(DOCTOR_CHAT_ID, 11), (ADMIN_CHAT_ID, 12), (DOCTOR_CHAT_ID, 13)]


@pytest.mark.asyncio
async def test_close_staff_request_keyboards_continues_after_a_failed_edit():
    """One unreachable chat (bot blocked, message deleted) must not swallow the rest."""
    appt_mng = MagicMock()
    appt_mng.get_invalidation_targets = AsyncMock(return_value=[
        AppointmentNotification(appointment_id=1, chat_id=DOCTOR_CHAT_ID, message_id=11, kind="booking"),
        AppointmentNotification(appointment_id=1, chat_id=ADMIN_CHAT_ID, message_id=12, kind="booking"),
    ])
    notification_service = MagicMock()
    notification_service.invalidate_closed_request_message = AsyncMock(
        side_effect=[RuntimeError("chat not found"), None]
    )

    await _close_staff_request_keyboards(
        appt_mng, notification_service, 1, ("booking",), _PENDING_EXPIRED_OUTCOME,
    )

    assert notification_service.invalidate_closed_request_message.await_count == 2


@pytest.mark.asyncio
async def test_close_staff_request_keyboards_skips_a_kind_whose_lookup_fails():
    appt_mng = MagicMock()
    appt_mng.get_invalidation_targets = AsyncMock(side_effect=[
        RuntimeError("db gone"),
        [AppointmentNotification(appointment_id=1, chat_id=ADMIN_CHAT_ID, message_id=12, kind="reschedule")],
    ])
    notification_service = MagicMock()
    notification_service.invalidate_closed_request_message = AsyncMock()

    await _close_staff_request_keyboards(
        appt_mng, notification_service, 1, ("booking", "reschedule"), _PENDING_EXPIRED_OUTCOME,
    )

    notification_service.invalidate_closed_request_message.assert_awaited_once_with(
        ADMIN_CHAT_ID, 12, _PENDING_EXPIRED_OUTCOME,
    )


@pytest.mark.asyncio
async def test_client_cancellation_closes_staff_request_keyboards():
    appointment = _appointment()

    appt_mng = MagicMock()
    appt_mng.cancel_appointment_by_client = AsyncMock(return_value=appointment)
    appt_mng.get_appointment_with_client_info = AsyncMock(return_value=(appointment, _client_user()))
    appt_mng.resolve_notification_recipients = AsyncMock(return_value=[])
    appt_mng.get_invalidation_targets = AsyncMock(side_effect=lambda appointment_id, kind, actor_chat_id: (
        [AppointmentNotification(appointment_id=1, chat_id=DOCTOR_CHAT_ID, message_id=11, kind="booking")]
        if kind == "booking" else []
    ))

    notification_service = MagicMock()
    notification_service.invalidate_closed_request_message = AsyncMock()

    router = create_client_appointment_router(
        MagicMock(), appointment_management_service=appt_mng, notification_service=notification_service,
    )
    manage_action = _find_handler(router, "manage_action")

    callback_query = MagicMock()
    callback_query.from_user.id = CLIENT_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()

    await manage_action(
        callback_query,
        ClientManageActionCB(action="cancel_yes", appointment_id=1, page=1),
        MagicMock(),
        _client_user(),
    )

    notification_service.invalidate_closed_request_message.assert_awaited_once_with(
        DOCTOR_CHAT_ID, 11, {"ru": "клиент отменил запись", "uz": "mijoz yozuvni bekor qildi"},
    )
