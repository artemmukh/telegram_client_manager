"""Handler-level tests for the new 3-button invite router (PR3).

bot/handlers/client/appointment_invite.py replaces the old confirm/cancel
buttons on the initial admin-created invite with a dedicated router
(AppointmentInviteActionCB: confirm/cancel), separate from the 2h-reminder
confirm/cancel handlers in appointment_response.py. Thin, direct-call tests in
the same style as test_appointment_reschedule_handler.py: build the router
with mock collaborators, pull the decorated callback out of
router.callback_query.handlers, and invoke it directly with mock aiogram
objects.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.client.appointment_invite import create_client_appointment_invite_router
from bot.keyboards.client.appointment_invite_cb import AppointmentInviteActionCB
from bot.models.appointment import Appointment
from bot.models.user import User
from bot.states.client.appointment_states import AppointmentResponseStates
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


def _get_handler_by_name(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"{name} handler not found on router")


def _client_user():
    return User(full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, telegram_user_id=555, ID=7)


def _appointment(status=AppointmentStatus.PENDING):
    return Appointment(
        clinic_id=1,
        client_id=7,
        datetime="2026-08-01 10:00",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=status,
        id=1,
        created_by_telegram_id=999,
    )


def _make_callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = 555
    callback_query.message.edit_text = AsyncMock()
    callback_query.answer = AsyncMock()
    return callback_query


def _make_state(appointment_id=1):
    state = MagicMock()
    state.get_data = AsyncMock(return_value={"appointment_id": appointment_id})
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    state.clear = AsyncMock()
    return state


def _build_router(
    appointment_management_service=None, notification_service=None, appointment_scheduler=None,
):
    return create_client_appointment_invite_router(
        appointment_management_service or MagicMock(),
        notification_service or MagicMock(),
        appointment_scheduler or MagicMock(),
    )


@pytest.mark.asyncio
async def test_confirm_invite_confirms_appointment_resyncs_jobs_and_notifies_admin():
    """confirm action: confirms the appointment, resyncs the full job set, and --
    unlike the 2h-reminder confirm handler -- still notifies the admin (this is the
    initial invite, the admin has not seen a client decision yet)."""
    confirmed_appointment = _appointment(AppointmentStatus.CONFIRMED)

    appointment_management_service = MagicMock()
    appointment_management_service.confirm_appointment_by_client = AsyncMock(return_value=confirmed_appointment)
    appointment_management_service.get_appointment_with_client_info = AsyncMock(
        return_value=(confirmed_appointment, _client_user())
    )

    notification_service = MagicMock()
    notification_service.notify_admin_confirmation = AsyncMock()

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()

    router = _build_router(appointment_management_service, notification_service, appointment_scheduler)
    confirm_invite = _get_handler_by_name(router, "confirm_invite")

    callback_query = _make_callback_query()
    await confirm_invite(callback_query, AppointmentInviteActionCB(action="confirm", appointment_id=1))

    appointment_management_service.confirm_appointment_by_client.assert_awaited_once_with(1, 555)
    appointment_scheduler.resync_appointment_jobs.assert_awaited_once_with(confirmed_appointment)

    callback_query.message.edit_text.assert_awaited_once_with("✅ Спасибо! Ваша запись подтверждена")
    assert "reply_markup" not in callback_query.message.edit_text.call_args.kwargs

    notification_service.notify_admin_confirmation.assert_awaited_once_with(
        999, confirmed_appointment, "Иванов Иван",
    )


@pytest.mark.asyncio
async def test_cancel_invite_ask_shows_confirmation_dialog_and_sets_state():
    """cancel action (first tap): shows a yes/no confirmation dialog and stashes
    appointment_id in FSM state -- does not cancel anything yet."""
    appointment_management_service = MagicMock()
    notification_service = MagicMock()
    appointment_scheduler = MagicMock()

    router = _build_router(appointment_management_service, notification_service, appointment_scheduler)
    cancel_invite_ask = _get_handler_by_name(router, "cancel_invite_ask")

    callback_query = _make_callback_query()
    state = _make_state()

    await cancel_invite_ask(
        callback_query, AppointmentInviteActionCB(action="cancel", appointment_id=1), state,
    )

    state.set_state.assert_awaited_once_with(AppointmentResponseStates.confirm_cancel)
    state.update_data.assert_awaited_once_with(appointment_id=1)
    callback_query.message.edit_text.assert_awaited_once()
    appointment_management_service.cancel_appointment_by_client.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_invite_yes_cancels_without_enforcing_cutoff_and_resyncs_jobs():
    """cancel confirmation YES: cancels the appointment with enforce_cutoff=False
    (this is the client backing out of an invite they never accepted, not a
    late cancellation of a confirmed visit), resyncs the full job set, and
    notifies the admin."""
    cancelled_appointment = _appointment(AppointmentStatus.CANCELLED)

    appointment_management_service = MagicMock()
    appointment_management_service.cancel_appointment_by_client = AsyncMock(return_value=cancelled_appointment)
    appointment_management_service.get_appointment_with_client_info = AsyncMock(
        return_value=(cancelled_appointment, _client_user())
    )

    notification_service = MagicMock()
    notification_service.notify_admin_cancellation = AsyncMock()

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()

    router = _build_router(appointment_management_service, notification_service, appointment_scheduler)
    cancel_invite_yes = _get_handler_by_name(router, "cancel_invite_yes")

    callback_query = _make_callback_query()
    state = _make_state(appointment_id=1)

    await cancel_invite_yes(callback_query, state)

    appointment_management_service.cancel_appointment_by_client.assert_awaited_once_with(
        1, 555, enforce_cutoff=False,
    )
    appointment_scheduler.resync_appointment_jobs.assert_awaited_once_with(cancelled_appointment)

    callback_query.message.edit_text.assert_awaited_once_with("✅ Ваша запись отменена")
    assert "reply_markup" not in callback_query.message.edit_text.call_args.kwargs

    notification_service.notify_admin_cancellation.assert_awaited_once_with(
        999, cancelled_appointment, "Иванов Иван",
    )
    state.clear.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_invite_no_reverts_to_invite_keyboard_without_cancelling():
    """cancel confirmation NO: backs out of the confirmation dialog, restores the
    3-button invite keyboard, and never touches the appointment."""
    appointment_management_service = MagicMock()
    notification_service = MagicMock()
    appointment_scheduler = MagicMock()

    router = _build_router(appointment_management_service, notification_service, appointment_scheduler)
    cancel_invite_no = _get_handler_by_name(router, "cancel_invite_no")

    callback_query = _make_callback_query()
    state = _make_state(appointment_id=1)

    await cancel_invite_no(callback_query, state)

    appointment_management_service.cancel_appointment_by_client.assert_not_called()
    appointment_scheduler.resync_appointment_jobs.assert_not_called()
    callback_query.message.edit_text.assert_awaited_once()
    assert callback_query.message.edit_text.call_args.args[0] == "Отмена отменена"
    state.clear.assert_awaited_once()
