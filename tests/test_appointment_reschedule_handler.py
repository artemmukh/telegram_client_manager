"""Handler-level test for submit_reschedule's is_direct_edit branching.

This is a thin, direct-call test: the router is built with fake/mock
collaborators, the decorated `submit_reschedule` callback is pulled out of
`router.callback_query.handlers` (aiogram's callback_query decorator returns
the callback unchanged, see TelegramEventObserver.__call__), and invoked
directly with mock aiogram objects. No dispatcher/polling infrastructure.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.client.appointment_reschedule import create_client_reschedule_router
from bot.keyboards.client.reschedule_cb import (
    ClientRescheduleDayCB,
    ClientRescheduleSlotCB,
    ClientRescheduleSubmitCB,
)
from bot.models.appointment import Appointment
from bot.models.appointment_notification import AppointmentNotification
from bot.models.user import User
from bot.states.client.reschedule_states import ClientRescheduleStates
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


def _get_handler_by_name(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"{name} handler not found on router")


def _get_submit_reschedule_handler(router):
    return _get_handler_by_name(router, "submit_reschedule")


def _client_user():
    return User(full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, telegram_user_id=555, ID=7)


def _appointment(status):
    return Appointment(
        clinic_id=1,
        client_id=7,
        datetime="2026-08-01 10:00",
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=status,
        id=1,
    )


def _make_callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = 555
    callback_query.message.edit_text = AsyncMock()
    callback_query.answer = AsyncMock()
    return callback_query


def _make_state():
    state = MagicMock()
    state.get_data = AsyncMock(return_value={"new_datetime": "2026-08-01 10:00", "origin": "manage", "page": 1})
    state.clear = AsyncMock()
    return state


@pytest.mark.asyncio
async def test_submit_reschedule_pending_client_booking_closes_old_card_and_sends_reschedule_request():
    """PENDING self-booking uses the same visible request card as other reschedules.

    The old booking action card is closed without touching historical compact logs;
    staff receive a fresh actionable reschedule notification and its delivery is
    persisted as ``reschedule``.
    """
    resulting_appointment = _appointment(AppointmentStatus.PENDING)
    resulting_appointment.proposed_datetime = "2026-08-02 10:00"
    resulting_appointment.proposed_by = CreatedBy.CLIENT

    appointment_management_service = MagicMock()
    appointment_management_service.request_reschedule_by_client = AsyncMock(return_value=resulting_appointment)
    appointment_management_service.resolve_notification_recipients = AsyncMock(
        return_value=[User(full_name="Врач", phone="+998900000000", role=Role.ADMIN, telegram_user_id=999, ID=42)]
    )
    appointment_management_service.get_active_notification_targets = AsyncMock(
        return_value=[AppointmentNotification(1, 777, 1, "booking", id=11)]
    )
    appointment_management_service.record_notification = AsyncMock()

    notification_service = MagicMock()
    notification_service.notify_admin_client_changed_time = AsyncMock()
    notification_service.notify_staff_reschedule_requested = AsyncMock(return_value=987)
    notification_service.invalidate_closed_request_message = AsyncMock()

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()
    appointment_scheduler.schedule_reschedule_expiry = AsyncMock()

    router = create_client_reschedule_router(
        appointment_management_service, notification_service, appointment_scheduler,
    )
    submit_reschedule = _get_submit_reschedule_handler(router)

    await submit_reschedule(
        _make_callback_query(), ClientRescheduleSubmitCB(appointment_id=1), _make_state(), _client_user(),
    )

    notification_service.notify_admin_client_changed_time.assert_not_awaited()
    notification_service.notify_staff_reschedule_requested.assert_awaited_once()
    appointment_management_service.get_active_notification_targets.assert_awaited_once_with(
        1, "booking",
    )
    notification_service.invalidate_closed_request_message.assert_awaited_once()
    assert notification_service.invalidate_closed_request_message.await_args.args[:2] == (777, 1)
    appointment_management_service.record_notification.assert_awaited_once_with(
        1, 999, 987, kind="reschedule",
    )

    appointment_scheduler.resync_appointment_jobs.assert_awaited_once_with(resulting_appointment)
    appointment_scheduler.schedule_reschedule_expiry.assert_not_awaited()


def _pending_reschedule_handler_dependencies(*, message_edit=None, delivery_id=987):
    resulting_appointment = _appointment(AppointmentStatus.PENDING)
    resulting_appointment.proposed_datetime = "2026-08-02 10:00"
    resulting_appointment.proposed_by = CreatedBy.CLIENT

    appointment_management_service = MagicMock()
    appointment_management_service.request_reschedule_by_client = AsyncMock(return_value=resulting_appointment)
    appointment_management_service.resolve_notification_recipients = AsyncMock(
        return_value=[User(full_name="Врач", phone="+998900000000", role=Role.ADMIN, telegram_user_id=999, ID=42)]
    )
    appointment_management_service.get_active_notification_targets = AsyncMock(
        return_value=[AppointmentNotification(1, 777, 1, "booking", id=11)]
    )
    appointment_management_service.record_notification = AsyncMock()
    appointment_management_service.withdraw_client_reschedule_proposal = AsyncMock()

    notification_service = MagicMock()
    notification_service.notify_staff_reschedule_requested = AsyncMock(return_value=delivery_id)
    notification_service.invalidate_closed_request_message = AsyncMock()

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()
    callback_query = _make_callback_query()
    if message_edit is not None:
        callback_query.message.edit_text = message_edit
    router = create_client_reschedule_router(
        appointment_management_service, notification_service, appointment_scheduler,
    )
    return router, callback_query, resulting_appointment, appointment_management_service, notification_service, appointment_scheduler


@pytest.mark.asyncio
async def test_submit_reschedule_with_no_staff_delivery_withdraws_proposal_and_resyncs_restored_appointment():
    router, callback_query, proposal, management, notifications, scheduler = _pending_reschedule_handler_dependencies(
        delivery_id=None,
    )
    restored = _appointment(AppointmentStatus.PENDING)
    restored.datetime = "2026-08-01 10:00"
    management.withdraw_client_reschedule_proposal.return_value = restored
    management.record_notification = AsyncMock()
    notifications.notify_staff_reschedule_requested = AsyncMock(return_value=None)
    submit = _get_submit_reschedule_handler(router)

    await submit(callback_query, ClientRescheduleSubmitCB(appointment_id=1), _make_state(), _client_user())

    management.withdraw_client_reschedule_proposal.assert_awaited_once()
    management.get_active_notification_targets.assert_not_awaited()
    notifications.invalidate_closed_request_message.assert_not_awaited()
    scheduler.resync_appointment_jobs.assert_awaited_once_with(restored)
    callback_query.message.edit_text.assert_awaited_once()
    failure_text = callback_query.message.edit_text.await_args.args[0]
    assert "не удалось" in failure_text.lower() or "не отправ" in failure_text.lower()


@pytest.mark.asyncio
async def test_submit_reschedule_with_withdrawal_race_shows_status_unknown_for_changed_current_booking():
    """A withdrawal CAS may lose to a concurrent staff time change. Even if the
    returned row is pending/client-created with no proposal, a changed datetime
    is not the original booking and must produce a neutral status message."""
    router, callback_query, proposal, management, notifications, scheduler = _pending_reschedule_handler_dependencies(
        delivery_id=None,
    )
    current = _appointment(AppointmentStatus.PENDING)
    current.datetime = "2026-08-03 10:00"
    management.withdraw_client_reschedule_proposal.return_value = current
    notifications.notify_staff_reschedule_requested = AsyncMock(return_value=None)
    submit = _get_submit_reschedule_handler(router)

    await submit(callback_query, ClientRescheduleSubmitCB(appointment_id=1), _make_state(), _client_user())

    scheduler.resync_appointment_jobs.assert_awaited_once_with(current)
    rendered_text = callback_query.message.edit_text.await_args.args[0]
    assert "Исходная заявка сохранена" not in rendered_text
    assert "Проверьте актуальный статус записи" in rendered_text


@pytest.mark.asyncio
async def test_submit_reschedule_delivery_record_failure_keeps_proposal_and_closes_old_cards():
    router, callback_query, proposal, management, notifications, scheduler = _pending_reschedule_handler_dependencies()
    management.record_notification.side_effect = RuntimeError("database unavailable")
    submit = _get_submit_reschedule_handler(router)

    await submit(callback_query, ClientRescheduleSubmitCB(appointment_id=1), _make_state(), _client_user())

    management.withdraw_client_reschedule_proposal.assert_not_awaited()
    management.get_active_notification_targets.assert_awaited_once_with(1, "booking")
    notifications.invalidate_closed_request_message.assert_awaited_once()
    assert notifications.invalidate_closed_request_message.await_args.args[:2] == (777, 1)
    scheduler.resync_appointment_jobs.assert_awaited_once_with(proposal)


@pytest.mark.asyncio
async def test_submit_reschedule_edit_failure_does_not_abort_staff_delivery_or_resync():
    failing_edit = AsyncMock(side_effect=RuntimeError("client message unavailable"))
    router, callback_query, proposal, management, notifications, scheduler = _pending_reschedule_handler_dependencies(
        message_edit=failing_edit,
    )
    submit = _get_submit_reschedule_handler(router)

    await submit(callback_query, ClientRescheduleSubmitCB(appointment_id=1), _make_state(), _client_user())

    notifications.notify_staff_reschedule_requested.assert_awaited_once()
    scheduler.resync_appointment_jobs.assert_awaited_once_with(proposal)


@pytest.mark.asyncio
async def test_submit_reschedule_negotiation_branch_notifies_staff_and_resyncs_jobs():
    """CONFIRMED result (negotiation): staff gets notify_staff_reschedule_requested,
    scheduler resyncs the full job set via resync_appointment_jobs (both branches call
    it unconditionally as of PR3) -- and the direct-edit-branch notification must NOT
    fire. Proves the is_direct_edit condition still branches on notifications even
    though the job-resync call itself is no longer branched."""
    resulting_appointment = _appointment(AppointmentStatus.CONFIRMED)
    # is_direct_edit is now discriminated by proposed_datetime (PR3), not status --
    # the negotiation branch requires an outstanding proposal to be set.
    resulting_appointment.proposed_datetime = "2026-08-02 10:00"
    resulting_appointment.proposed_by = CreatedBy.CLIENT

    appointment_management_service = MagicMock()
    appointment_management_service.request_reschedule_by_client = AsyncMock(return_value=resulting_appointment)
    appointment_management_service.resolve_notification_recipients = AsyncMock(
        return_value=[User(full_name="Врач", phone="+998900000000", role=Role.ADMIN, telegram_user_id=999, ID=42)]
    )

    notification_service = MagicMock()
    notification_service.notify_admin_client_changed_time = AsyncMock()
    notification_service.notify_staff_reschedule_requested = AsyncMock()

    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()
    appointment_scheduler.schedule_reschedule_expiry = AsyncMock()

    router = create_client_reschedule_router(
        appointment_management_service, notification_service, appointment_scheduler,
    )
    submit_reschedule = _get_submit_reschedule_handler(router)
    callback_query = _make_callback_query()

    await submit_reschedule(
        callback_query, ClientRescheduleSubmitCB(appointment_id=1), _make_state(), _client_user(),
    )

    notification_service.notify_staff_reschedule_requested.assert_awaited_once()
    notification_service.notify_admin_client_changed_time.assert_not_awaited()

    appointment_scheduler.resync_appointment_jobs.assert_awaited_once_with(resulting_appointment)
    appointment_scheduler.schedule_reschedule_expiry.assert_not_awaited()

    # Toast shows both the original confirmed time and the newly proposed time.
    toast_text = callback_query.message.edit_text.call_args.args[0]
    assert "1 августа 2026, 10:00" in toast_text
    assert "2 августа 2026, 10:00" in toast_text


@pytest.mark.asyncio
async def test_pick_day_with_malformed_day_iso_shows_alert_and_does_not_touch_state_or_slots():
    """Defensive guard around date.fromisoformat(callback_data.day_iso): a
    malformed/forged day_iso must short-circuit before any slot lookup or
    state mutation, and answer with a show_alert toast instead of crashing."""
    appointment_management_service = MagicMock()
    appointment_management_service.get_available_slots = AsyncMock()

    notification_service = MagicMock()
    appointment_scheduler = MagicMock()

    router = create_client_reschedule_router(
        appointment_management_service, notification_service, appointment_scheduler,
    )
    pick_day = _get_handler_by_name(router, "pick_day")

    callback_query = _make_callback_query()
    state = _make_state()

    await pick_day(
        callback_query,
        ClientRescheduleDayCB(appointment_id=1, week_offset=0, day_iso="not-a-date"),
        state,
        _client_user(),
    )

    callback_query.answer.assert_called_once_with("Некорректная дата, попробуйте ещё раз.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    state.update_data.assert_not_called()
    appointment_management_service.get_available_slots.assert_not_called()


@pytest.mark.asyncio
async def test_pick_slot_with_malformed_slot_shows_alert_and_does_not_touch_state():
    """Defensive guard around datetime.fromisoformat(new_datetime): a malformed
    slot must short-circuit before any state mutation, and answer with a
    show_alert toast instead of crashing."""
    appointment_management_service = MagicMock()
    notification_service = MagicMock()
    appointment_scheduler = MagicMock()

    router = create_client_reschedule_router(
        appointment_management_service, notification_service, appointment_scheduler,
    )
    pick_slot = _get_handler_by_name(router, "pick_slot")

    callback_query = _make_callback_query()
    state = _make_state()
    state.get_data = AsyncMock(return_value={"day_iso": "2026-08-01"})

    await pick_slot(
        callback_query,
        ClientRescheduleSlotCB(appointment_id=1, slot="xx:yy"),
        state,
        _client_user(),
    )

    callback_query.answer.assert_called_once_with("Некорректное время, попробуйте ещё раз.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    state.update_data.assert_not_called()
    state.set_state.assert_not_called()


@pytest.mark.asyncio
async def test_pick_slot_with_valid_slot_updates_state_and_renders_confirm_screen():
    """Regression guard for the fromisoformat reorder: a well-formed slot must
    still update state and render the confirmation screen as before."""
    appointment_management_service = MagicMock()
    notification_service = MagicMock()
    appointment_scheduler = MagicMock()

    router = create_client_reschedule_router(
        appointment_management_service, notification_service, appointment_scheduler,
    )
    pick_slot = _get_handler_by_name(router, "pick_slot")

    callback_query = _make_callback_query()
    state = _make_state()
    state.get_data = AsyncMock(return_value={"day_iso": "2026-08-01"})
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    await pick_slot(
        callback_query,
        ClientRescheduleSlotCB(appointment_id=1, slot="10:00"),
        state,
        _client_user(),
    )

    state.update_data.assert_awaited_once_with(slot="10:00", new_datetime="2026-08-01 10:00")
    state.set_state.assert_awaited_once_with(ClientRescheduleStates.confirm)
    callback_query.message.edit_text.assert_called_once()
    callback_query.answer.assert_called_once_with()


# --- pick_day: no-slots-for-day alert (shared helper) ---

def _pick_day_state(doctor_id=42, appointment_id=1):
    state = MagicMock()
    state.get_data = AsyncMock(return_value={"doctor_id": doctor_id, "appointment_id": appointment_id})
    return state


@pytest.mark.asyncio
async def test_pick_day_with_no_slots_shows_generic_client_wording():
    """Client wording ("На этот день больше нет доступных слотов.") is
    distinct from the admin wording -- pinned via bot.messages.booking."""
    import bot.messages.booking as msg

    appointment_management_service = MagicMock()
    appointment_management_service.get_available_slots = AsyncMock(return_value=[])
    appointment_management_service.get_day_block_reason = AsyncMock(return_value=None)

    router = create_client_reschedule_router(appointment_management_service, MagicMock(), MagicMock())
    pick_day = _get_handler_by_name(router, "pick_day")

    callback_query = _make_callback_query()
    state = _pick_day_state()

    await pick_day(
        callback_query,
        ClientRescheduleDayCB(appointment_id=1, week_offset=0, day_iso="2026-08-01"),
        state,
        _client_user(),
    )

    callback_query.answer.assert_called_once_with(msg.no_slots_for_day("ru"), show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    appointment_management_service.get_available_slots.assert_awaited_once()
    doctor_id_kw = appointment_management_service.get_available_slots.await_args.kwargs.get("exclude_appointment_id")
    assert doctor_id_kw == 1


@pytest.mark.asyncio
async def test_pick_day_with_blocked_day_shows_block_reason_unescaped():
    """callback_query.answer(show_alert=True) has no parse_mode -- a reason
    with '<' must reach it verbatim."""
    appointment_management_service = MagicMock()
    appointment_management_service.get_available_slots = AsyncMock(return_value=[])
    appointment_management_service.get_day_block_reason = AsyncMock(return_value="Ремонт <кабинет>")

    router = create_client_reschedule_router(appointment_management_service, MagicMock(), MagicMock())
    pick_day = _get_handler_by_name(router, "pick_day")

    callback_query = _make_callback_query()
    state = _pick_day_state(doctor_id=42, appointment_id=1)

    await pick_day(
        callback_query,
        ClientRescheduleDayCB(appointment_id=1, week_offset=0, day_iso="2026-08-01"),
        state,
        _client_user(),
    )

    toast_text = callback_query.answer.call_args.args[0]
    assert "<кабинет>" in toast_text
    assert "&lt;" not in toast_text
    doctor_id_arg, day_arg, _now_arg = appointment_management_service.get_day_block_reason.await_args.args
    assert doctor_id_arg == 42
    assert day_arg.isoformat() == "2026-08-01"
