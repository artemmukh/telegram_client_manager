"""Handler-level tests for the client self-booking submission flow
(bot/handlers/client/appointment_booking.py::submit_booking).

Before the notification-routing refactor this handler had NO dedicated test
file at all -- coverage only existed at the AppointmentNotificationService
level (test_appointment_notifications.py::test_notify_staff_new_booking_request_*).
These tests close that gap, following the same direct-handler-call convention
used in test_appointment_invite_handler.py: build the router with mock
collaborators, pull the decorated callback out of router.callback_query.handlers,
and invoke it directly with mock aiogram objects.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.client.appointment_booking import create_client_booking_router
from bot.keyboards.client.booking_cb import ClientBookDayCB, ClientBookSlotCB
from bot.models.appointment import Appointment
from bot.models.user import User
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.reply_menu_labels import REPLY_MENU_TEXT_MESSAGE
from bot.utils.role import Role


def _get_handler_by_name(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"{name} handler not found on router")


def _get_message_handler_by_name(router, name):
    for handler in router.message.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"{name} handler not found on router")


def _current_user():
    return User(full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, telegram_user_id=555, ID=7)


def _created_appointment():
    return Appointment(
        clinic_id=1,
        client_id=7,
        doctor_id=42,
        datetime="2026-08-01 10:00",
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=AppointmentStatus.PENDING,
        id=1,
    )


def _doctor():
    return User(full_name="Врач", phone="+998900000000", role=Role.ADMIN, telegram_user_id=555555, ID=42)


def _clinic_admin(telegram_user_id, admin_id):
    return User(
        full_name="Админ клиники", phone="+998900000001", role=Role.ADMIN,
        telegram_user_id=telegram_user_id, ID=admin_id,
    )


def _make_callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = 555
    callback_query.message.edit_text = AsyncMock()
    callback_query.answer = AsyncMock()
    return callback_query


def _make_state(staff_user_id=42, appointment_datetime="2026-08-01 10:00", complaint="Консультация"):
    state = MagicMock()
    state.get_data = AsyncMock(return_value={
        "staff_user_id": staff_user_id,
        "appointment_datetime": appointment_datetime,
        "complaint": complaint,
    })
    state.clear = AsyncMock()
    return state


def _build_router(appointment_management_service, notification_service, appointment_scheduler=None):
    return create_client_booking_router(
        appointment_management_service, notification_service, appointment_scheduler or AsyncMock(),
    )


@pytest.mark.asyncio
async def test_submit_booking_notifies_sole_doctor_recipient_and_persists_message_id():
    """Regression/backward-compat case: a single resolved recipient (the treating
    doctor) gets notified and their message_id is persisted via
    update_admin_notification_message_id -- matches the pre-refactor
    single-recipient behavior."""
    created_appointment = _created_appointment()
    doctor = _doctor()

    appointment_management_service = MagicMock()
    appointment_management_service.create_self_booking = AsyncMock(return_value=created_appointment)
    appointment_management_service.resolve_notification_recipients = AsyncMock(return_value=[doctor])
    appointment_management_service.update_admin_notification_message_id = AsyncMock()

    notification_service = MagicMock()
    notification_service.notify_staff_new_booking_request = AsyncMock(return_value=4242)

    appointment_scheduler = MagicMock()
    appointment_scheduler.schedule_pending_expiry = AsyncMock()

    router = _build_router(appointment_management_service, notification_service, appointment_scheduler)
    submit_booking = _get_handler_by_name(router, "submit_booking")

    await submit_booking(_make_callback_query(), _make_state(), _current_user())

    notification_service.notify_staff_new_booking_request.assert_awaited_once_with(
        doctor.telegram_user_id, created_appointment, "Иванов Иван",
    )
    appointment_management_service.update_admin_notification_message_id.assert_awaited_once_with(
        created_appointment.id, 4242,
    )
    appointment_scheduler.schedule_pending_expiry.assert_awaited_once_with(created_appointment)


@pytest.mark.asyncio
async def test_submit_booking_persists_only_the_first_successful_recipients_message_id():
    """With two resolved recipients, both are notified, but
    admin_notification_message_id (a single column that can only reply-thread to
    one recipient chat) is only ever set from the FIRST successful send -- the
    second recipient message_id must never overwrite it."""
    created_appointment = _created_appointment()
    doctor = _doctor()
    clinic_admin = _clinic_admin(999, 100)

    appointment_management_service = MagicMock()
    appointment_management_service.create_self_booking = AsyncMock(return_value=created_appointment)
    appointment_management_service.resolve_notification_recipients = AsyncMock(
        return_value=[doctor, clinic_admin]
    )
    appointment_management_service.update_admin_notification_message_id = AsyncMock()

    notification_service = MagicMock()
    notification_service.notify_staff_new_booking_request = AsyncMock(side_effect=[100, 200])

    router = _build_router(appointment_management_service, notification_service)
    submit_booking = _get_handler_by_name(router, "submit_booking")

    await submit_booking(_make_callback_query(), _make_state(), _current_user())

    assert notification_service.notify_staff_new_booking_request.await_count == 2
    appointment_management_service.update_admin_notification_message_id.assert_awaited_once_with(
        created_appointment.id, 100,
    )


@pytest.mark.asyncio
async def test_submit_booking_attempts_second_recipient_after_first_fails_and_persists_its_message_id():
    """Per-recipient failure isolation: the first recipient send raising must
    not stop the loop -- the second recipient is still attempted, and since the
    first recipient never produced a message_id, the second message_id is what
    gets persisted."""
    created_appointment = _created_appointment()
    doctor = _doctor()
    clinic_admin = _clinic_admin(999, 100)

    appointment_management_service = MagicMock()
    appointment_management_service.create_self_booking = AsyncMock(return_value=created_appointment)
    appointment_management_service.resolve_notification_recipients = AsyncMock(
        return_value=[doctor, clinic_admin]
    )
    appointment_management_service.update_admin_notification_message_id = AsyncMock()

    notification_service = MagicMock()
    notification_service.notify_staff_new_booking_request = AsyncMock(
        side_effect=[Exception("boom"), 300]
    )

    router = _build_router(appointment_management_service, notification_service)
    submit_booking = _get_handler_by_name(router, "submit_booking")

    # Should not raise, despite the first recipient send failing.
    await submit_booking(_make_callback_query(), _make_state(), _current_user())

    assert notification_service.notify_staff_new_booking_request.await_count == 2
    appointment_management_service.update_admin_notification_message_id.assert_awaited_once_with(
        created_appointment.id, 300,
    )


@pytest.mark.asyncio
async def test_submit_booking_does_not_notify_when_notification_service_missing():
    created_appointment = _created_appointment()

    appointment_management_service = MagicMock()
    appointment_management_service.create_self_booking = AsyncMock(return_value=created_appointment)
    appointment_management_service.resolve_notification_recipients = AsyncMock(return_value=[_doctor()])

    router = create_client_booking_router(appointment_management_service, None, AsyncMock())
    submit_booking = _get_handler_by_name(router, "submit_booking")

    await submit_booking(_make_callback_query(), _make_state(), _current_user())

    appointment_management_service.resolve_notification_recipients.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_booking_swallows_recipient_resolution_failure_and_skips_notifications(caplog):
    """If resolve_notification_recipients itself raises (e.g. a doctor/clinic
    lookup blows up), submit_booking must not crash -- it logs and falls back
    to an empty recipient list, so no notification send is attempted and the
    booking confirmation to the client (already sent above) still stands."""
    created_appointment = _created_appointment()

    appointment_management_service = MagicMock()
    appointment_management_service.create_self_booking = AsyncMock(return_value=created_appointment)
    appointment_management_service.resolve_notification_recipients = AsyncMock(
        side_effect=Exception("lookup boom")
    )

    notification_service = MagicMock()
    notification_service.notify_staff_new_booking_request = AsyncMock()

    router = _build_router(appointment_management_service, notification_service)
    submit_booking = _get_handler_by_name(router, "submit_booking")

    with caplog.at_level("ERROR"):
        await submit_booking(_make_callback_query(), _make_state(), _current_user())

    notification_service.notify_staff_new_booking_request.assert_not_awaited()
    assert "Failed to resolve notification recipients" in caplog.text


@pytest.mark.asyncio
async def test_pick_day_with_malformed_day_iso_shows_alert_and_does_not_touch_state_or_slots():
    """Defensive guard around date.fromisoformat(callback_data.day_iso): a
    malformed/forged day_iso must short-circuit before any slot lookup or
    state mutation, and answer with a show_alert toast instead of crashing."""
    appointment_management_service = MagicMock()
    appointment_management_service.get_available_slots = AsyncMock()

    notification_service = MagicMock()

    router = _build_router(appointment_management_service, notification_service)
    pick_day = _get_handler_by_name(router, "pick_day")

    callback_query = _make_callback_query()
    state = _make_state()

    await pick_day(
        callback_query, ClientBookDayCB(week_offset=0, day_iso="not-a-date"), state, _current_user(),
    )

    callback_query.answer.assert_called_once_with("Некорректная дата, попробуйте ещё раз.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    state.update_data.assert_not_called()
    appointment_management_service.get_available_slots.assert_not_called()


@pytest.mark.asyncio
async def test_pick_slot_with_malformed_slot_shows_alert_and_does_not_touch_state():
    """Defensive guard around datetime.strptime(callback_data.slot, "%H:%M"):
    a malformed/forged slot must short-circuit before any state mutation --
    previously pick_slot stored the raw slot unchecked and only crashed later,
    inside process_complaint's build_booking_confirmation_text, after the FSM
    had already advanced to ClientBookingStates.complaint."""
    appointment_management_service = MagicMock()
    notification_service = MagicMock()

    router = _build_router(appointment_management_service, notification_service)
    pick_slot = _get_handler_by_name(router, "pick_slot")

    callback_query = _make_callback_query()
    state = _make_state()

    await pick_slot(callback_query, ClientBookSlotCB(slot="xx:yy"), state, _current_user())

    callback_query.answer.assert_called_once_with("Некорректное время, попробуйте ещё раз.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    state.get_data.assert_not_called()
    state.update_data.assert_not_called()
    state.set_state.assert_not_called()


@pytest.mark.asyncio
async def test_pick_slot_with_valid_slot_updates_state_and_renders_complaint_prompt():
    """Regression coverage for the success path: a well-formed slot still
    updates state and advances to ClientBookingStates.complaint as before."""
    from bot.states.client.booking_states import ClientBookingStates

    appointment_management_service = MagicMock()
    notification_service = MagicMock()

    router = _build_router(appointment_management_service, notification_service)
    pick_slot = _get_handler_by_name(router, "pick_slot")

    callback_query = _make_callback_query()
    state = MagicMock()
    state.get_data = AsyncMock(return_value={"day_iso": "2026-08-01"})
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    await pick_slot(callback_query, ClientBookSlotCB(slot="10:00"), state, _current_user())

    state.update_data.assert_awaited_once_with(
        slot="10:00", appointment_datetime="2026-08-01 10:00",
    )
    state.set_state.assert_awaited_once_with(ClientBookingStates.complaint)
    callback_query.message.edit_text.assert_called_once()
    callback_query.answer.assert_called_once()


@pytest.mark.asyncio
async def test_process_complaint_with_reply_menu_button_label_shows_special_message_instead_of_accepting_it():
    """Tapping a persistent reply-keyboard button (e.g. the client main menu's
    price-list button) while the FSM is awaiting the free-text complaint must
    not be silently accepted as the complaint text -- process_complaint calls
    validate_purpose directly (not the shared purpose_processing helper), so
    this is the one entry point that would otherwise corrupt the appointment's
    purpose with a button label."""
    appointment_management_service = MagicMock()
    notification_service = MagicMock()

    router = _build_router(appointment_management_service, notification_service)
    process_complaint = _get_message_handler_by_name(router, "process_complaint")

    message = MagicMock()
    message.text = "📋 Прайс-лист"
    message.answer = AsyncMock()

    state = MagicMock()
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()

    await process_complaint(message, state, _current_user())

    message.answer.assert_awaited_once_with(REPLY_MENU_TEXT_MESSAGE["ru"])
    state.update_data.assert_not_awaited()
    state.set_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_complaint_with_ordinary_text_is_accepted_as_before():
    appointment_management_service = MagicMock()
    notification_service = MagicMock()

    router = _build_router(appointment_management_service, notification_service)
    process_complaint = _get_message_handler_by_name(router, "process_complaint")

    message = MagicMock()
    message.text = "Болит зуб"
    message.answer = AsyncMock()

    state = MagicMock()
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.get_data = AsyncMock(return_value={"staff_name": "Врач", "day_iso": "2026-08-01", "slot": "10:00"})

    await process_complaint(message, state, _current_user())

    state.update_data.assert_awaited_once_with(complaint="Болит зуб")
    message.answer.assert_awaited_once()


# --- pick_day: no-slots-for-day alert (shared helper) ---

@pytest.mark.asyncio
async def test_pick_day_with_no_slots_shows_generic_client_wording():
    """Client wording ("На этот день больше нет доступных слотов.") is
    distinct from the admin wording -- pinned via bot.messages.booking."""
    import bot.messages.booking as msg

    appointment_management_service = MagicMock()
    appointment_management_service.get_available_slots = AsyncMock(return_value=[])
    appointment_management_service.get_day_block_reason = AsyncMock(return_value=None)

    router = _build_router(appointment_management_service, MagicMock())
    pick_day = _get_handler_by_name(router, "pick_day")

    callback_query = _make_callback_query()
    state = _make_state()

    await pick_day(
        callback_query, ClientBookDayCB(week_offset=0, day_iso="2026-08-01"), state, _current_user(),
    )

    callback_query.answer.assert_called_once_with(msg.no_slots_for_day("ru"), show_alert=True)
    callback_query.message.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_pick_day_with_blocked_day_shows_block_reason_unescaped():
    """callback_query.answer(show_alert=True) has no parse_mode -- a reason
    with '<' must reach it verbatim."""
    appointment_management_service = MagicMock()
    appointment_management_service.get_available_slots = AsyncMock(return_value=[])
    appointment_management_service.get_day_block_reason = AsyncMock(return_value="Ремонт <кабинет>")

    router = _build_router(appointment_management_service, MagicMock())
    pick_day = _get_handler_by_name(router, "pick_day")

    callback_query = _make_callback_query()
    state = _make_state()

    await pick_day(
        callback_query, ClientBookDayCB(week_offset=0, day_iso="2026-08-01"), state, _current_user(),
    )

    toast_text = callback_query.answer.call_args.args[0]
    assert "<кабинет>" in toast_text
    assert "&lt;" not in toast_text
    doctor_id_arg, day_arg, _now_arg = appointment_management_service.get_day_block_reason.await_args.args
    assert doctor_id_arg == 42
    assert day_arg.isoformat() == "2026-08-01"
