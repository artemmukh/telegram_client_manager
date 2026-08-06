"""Handler-level tests for the admin slot-blocking router
(bot/handlers/admin/appointment_management/slot_blocking.py), focused on
confirm_block_creation: the branch that turns a rejected create_block() into a
redrawn blocking menu instead of leaving the admin stranded on a dead
confirmation screen.

Follows the direct-handler-call/fake-repository convention established in
tests/test_booking_requests_calendar_slot_picker.py.
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from bot.handlers.admin.appointment_management.slot_blocking import (
    _CANCELABLE_CONFLICTS_TOO_LONG_TEXT,
    _PROPOSED_CONFLICTS_COUNT_ONLY_TEXT,
    _TELEGRAM_MESSAGE_LIMIT,
    create_admin_slot_blocking_router,
)
from bot.keyboards.admin.record_management_kb.appointment_kb import back_to_records_kb
from bot.keyboards.admin.record_management_kb.slot_blocking_cb import SlotBlockConfirmCB
from bot.keyboards.admin.record_management_kb.slot_blocking_kb import (
    slot_blocking_confirm_kb,
    slot_blocking_menu_kb,
)
from bot.models.appointment import Appointment
from bot.models.blocked_slot import BlockedSlot
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.services.utils.date_parser import (
    format_appointment_card_datetime,
    format_datetime_for_db,
    get_current_tashkent_datetime,
)
from bot.states.admin.record_management.slot_blocking_states import SlotBlockCreationStates
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role
from tests.conftest import FakeBlockedSlotRepository

ADMIN_TELEGRAM_ID = 999
CLINIC_ID = 1
DOCTOR_ID = 42

_MENU_TEXT = "🚫 Блокировка слотов"
_BLOCK_CREATED_TEXT = "✅ Блокировка создана."


class FakeAppointmentRepository:
    def __init__(self, appointments=None):
        self.appointments = list(appointments or [])
        self.status_updates = []

    async def get_appointments_in_range(self, clinic_id, doctor_id, start_datetime, end_datetime):
        return [
            a for a in self.appointments
            if a.clinic_id == clinic_id
            and (doctor_id is None or a.doctor_id == doctor_id)
            and start_datetime <= a.datetime < end_datetime
        ]

    async def get_appointments_with_proposed_datetime_in_range(
        self, clinic_id, doctor_id, start_datetime, end_datetime,
    ):
        matches = [
            a for a in self.appointments
            if a.clinic_id == clinic_id
            and (doctor_id is None or a.doctor_id == doctor_id)
            and a.proposed_datetime is not None
            and start_datetime <= a.proposed_datetime < end_datetime
        ]
        return sorted(matches, key=lambda a: a.proposed_datetime)

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.status_updates.append((appointment_id, status))


class FakeUserRepo:
    def __init__(self, admin=None):
        self.admin = admin

    async def get_user_by_telegram_id(self, telegram_user_id):
        if self.admin is not None and self.admin.telegram_user_id == telegram_user_id:
            return self.admin
        return None

    async def get_user_by_id(self, user_id):
        if self.admin is not None and self.admin.ID == user_id:
            return self.admin
        return None

    async def get_staff_users_by_clinic_id(self, clinic_id):
        return [self.admin] if self.admin is not None else []


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=CLINIC_ID, visibility_scope="clinic")

    async def get_staff_by_clinic_id(self, clinic_id):
        return [await self.get_staff(ADMIN_TELEGRAM_ID)]


class FakeClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=CLINIC_ID, name="Зуб Мудрости", token="t")


def _admin_user():
    return User(
        full_name="Петров Петр", phone="+998907654321", role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID, ID=DOCTOR_ID, clinic_id=CLINIC_ID, clinic_name="Зуб Мудрости",
    )


def _build_router(blocked_slot_repo=None, appt_repo=None):
    return create_admin_slot_blocking_router(
        FakeUserRepo(_admin_user()),
        FakeStaffRepo(),
        FakeClinicRepo(),
        appt_repo if appt_repo is not None else FakeAppointmentRepository(),
        blocked_slot_repo if blocked_slot_repo is not None else FakeBlockedSlotRepository(),
    )


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _find_message_handler(router, name):
    for handler in router.message.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"message handler {name} not found")


def _message(text):
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    return message


def _callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _state(**data):
    state = MagicMock()
    state.get_data = AsyncMock(return_value=data)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


def _raw_range(offset_days, hour=10, duration_hours=1):
    start_dt = get_current_tashkent_datetime().replace(
        hour=hour, minute=0, second=0, microsecond=0,
    ) + timedelta(days=offset_days)
    end_dt = start_dt + timedelta(hours=duration_hours)
    return start_dt.strftime("%d.%m.%Y %H:%M"), end_dt.strftime("%d.%m.%Y %H:%M")


# --- confirm_block_creation ---

@pytest.mark.asyncio
async def test_confirm_block_creation_redraws_the_blocking_menu_when_the_service_rejects_the_block():
    """A fully past range makes create_block raise InvalidBlockRangeError. The
    admin must land back on the blocking menu with a cleared state, not on a
    stale confirmation screen whose buttons no longer do anything."""
    blocked_slot_repo = FakeBlockedSlotRepository()
    router = _build_router(blocked_slot_repo)
    confirm_block_creation = _find_handler(router, "confirm_block_creation")

    start_raw, end_raw = _raw_range(offset_days=-1)
    callback_query = _callback_query()
    state = _state(
        clinic_id=CLINIC_ID, staff_id=DOCTOR_ID,
        range_start_raw=start_raw, range_end_raw=end_raw,
        range_start="", range_end="", reason="Отпуск",
    )

    await confirm_block_creation(
        callback_query, SlotBlockConfirmCB(action="create"), state, _admin_user(),
    )

    assert blocked_slot_repo.blocks == []
    state.clear.assert_awaited_once()
    callback_query.answer.assert_awaited_once_with(
        "Нельзя заблокировать полностью прошедший интервал.", show_alert=True,
    )
    callback_query.message.edit_text.assert_awaited_once_with(
        _MENU_TEXT, reply_markup=slot_blocking_menu_kb(lang="ru"),
    )


@pytest.mark.asyncio
async def test_confirm_block_creation_reports_success_on_a_valid_range():
    """Contrast case for the rejection test above: a valid range must NOT land
    on the blocking menu."""
    blocked_slot_repo = FakeBlockedSlotRepository()
    router = _build_router(blocked_slot_repo)
    confirm_block_creation = _find_handler(router, "confirm_block_creation")

    start_raw, end_raw = _raw_range(offset_days=2)
    callback_query = _callback_query()
    state = _state(
        clinic_id=CLINIC_ID, staff_id=DOCTOR_ID,
        range_start_raw=start_raw, range_end_raw=end_raw,
        range_start="", range_end="", reason="Отпуск",
    )

    await confirm_block_creation(
        callback_query, SlotBlockConfirmCB(action="create"), state, _admin_user(),
    )

    assert len(blocked_slot_repo.blocks) == 1
    assert blocked_slot_repo.blocks[0].reason == "Отпуск"
    callback_query.message.edit_text.assert_awaited_once_with(
        _BLOCK_CREATED_TEXT, reply_markup=back_to_records_kb(lang="ru"),
    )
    state.clear.assert_awaited_once()


# --- get_reason: proposed-datetime conflicts (report-only, never gate confirm_conflicts) ---

def _db_range(offset_days=2, hour=10, duration_hours=1):
    start_dt = get_current_tashkent_datetime().replace(
        hour=hour, minute=0, second=0, microsecond=0,
    ) + timedelta(days=offset_days)
    end_dt = start_dt + timedelta(hours=duration_hours)
    return format_datetime_for_db(start_dt), format_datetime_for_db(end_dt)


def _conflict_appointment(
    appointment_id, dt, proposed_dt=None, status=AppointmentStatus.PENDING, client_full_name="Иванов Иван",
):
    appointment = Appointment(
        clinic_id=CLINIC_ID, client_id=7, doctor_id=DOCTOR_ID, datetime=dt, purpose="Consultation",
        created_by=CreatedBy.CLIENT, status=status, id=appointment_id, client_full_name=client_full_name,
    )
    if proposed_dt is not None:
        appointment.proposed_datetime = proposed_dt
        appointment.proposed_by = CreatedBy.CLIENT
    return appointment


@pytest.mark.asyncio
async def test_get_reason_proposal_only_conflict_stays_on_confirm_block_with_no_conflicts_flag():
    """An appointment whose current time is free but whose proposed reschedule
    falls inside the block range must NOT flip has_conflicts or route into
    confirm_conflicts -- it only adds an additive warning block to the plain
    confirm_block screen."""
    range_start, range_end = _db_range()
    outside_dt = "2020-01-01 08:00"
    appointment = _conflict_appointment(appointment_id=1, dt=outside_dt, proposed_dt=range_start)
    router = _build_router(appt_repo=FakeAppointmentRepository([appointment]))
    get_reason = _find_message_handler(router, "get_reason")

    message = _message("Ремонт")
    state = _state(clinic_id=CLINIC_ID, staff_id=DOCTOR_ID, range_start=range_start, range_end=range_end)

    await get_reason(message, state, _admin_user())

    state.set_state.assert_awaited_once_with(SlotBlockCreationStates.confirm_block)
    message.answer.assert_awaited_once()
    text = message.answer.call_args.args[0]
    reply_markup = message.answer.call_args.kwargs["reply_markup"]

    assert reply_markup == slot_blocking_confirm_kb(lang="ru", has_conflicts=False)
    assert "Иванов Иван" in text  # the proposal-conflict line is rendered
    assert "Создать блокировку с" in text  # confirm_block's own question is present
    assert "Продолжить создание блокировки?" not in text  # cancelable-branch footer must not also appear


@pytest.mark.asyncio
async def test_get_reason_dedupes_appointment_present_in_both_cancelable_and_proposed_lists():
    """An appointment whose CURRENT datetime and PROPOSED datetime are both
    inside the block range must be reported exactly once -- in the cancelable
    list (which drives the "will be cancelled" copy) -- not duplicated into
    the additive proposal-conflicts block. The two instants are deliberately
    DIFFERENT (not both == range_start) so the two lines would render with
    distinguishable datetimes if the dedupe filter were ever removed, instead
    of silently matching on an identical duplicate line."""
    range_start, range_end = _db_range()  # 1-hour range: [range_start, range_start + 1h)
    range_start_dt = datetime.strptime(range_start, "%Y-%m-%d %H:%M")
    proposed_dt = format_datetime_for_db(range_start_dt + timedelta(minutes=30))  # still inside [range_start, range_end)
    appointment = _conflict_appointment(appointment_id=1, dt=range_start, proposed_dt=proposed_dt)
    router = _build_router(appt_repo=FakeAppointmentRepository([appointment]))
    get_reason = _find_message_handler(router, "get_reason")

    message = _message("Ремонт")
    state = _state(clinic_id=CLINIC_ID, staff_id=DOCTOR_ID, range_start=range_start, range_end=range_end)

    await get_reason(message, state, _admin_user())

    state.set_state.assert_awaited_once_with(SlotBlockCreationStates.confirm_conflicts)
    text = message.answer.call_args.args[0]
    reply_markup = message.answer.call_args.kwargs["reply_markup"]

    assert reply_markup == slot_blocking_confirm_kb(lang="ru", has_conflicts=True)
    assert text.count("Иванов Иван") == 1  # appears once, not duplicated into a second block
    assert "предложение переноса" not in text  # the proposed-conflicts header never rendered
    # The PROPOSED instant specifically must not be rendered anywhere -- only
    # the cancelable list (keyed on the appointment's current datetime) shows.
    assert format_appointment_card_datetime(proposed_dt) not in text
    assert format_appointment_card_datetime(range_start) in text
    assert text.endswith("Продолжить создание блокировки?")


@pytest.mark.asyncio
async def test_get_reason_cancelable_branch_ends_with_its_question_even_with_a_proposal_block_present():
    """Exactly one question per screen: when both a cancelable conflict and a
    separate proposal-only conflict are present, the proposal block is
    inserted BEFORE the footer, so the message still ends with the
    cancelable-branch's own closing question."""
    range_start, range_end = _db_range()
    cancelable = _conflict_appointment(
        appointment_id=1, dt=range_start, client_full_name="Cancelable Client",
    )
    proposal_only = _conflict_appointment(
        appointment_id=2, dt="2020-01-01 08:00", proposed_dt=range_start, client_full_name="Proposal Client",
    )
    router = _build_router(appt_repo=FakeAppointmentRepository([cancelable, proposal_only]))
    get_reason = _find_message_handler(router, "get_reason")

    message = _message("Ремонт")
    state = _state(clinic_id=CLINIC_ID, staff_id=DOCTOR_ID, range_start=range_start, range_end=range_end)

    await get_reason(message, state, _admin_user())

    state.set_state.assert_awaited_once_with(SlotBlockCreationStates.confirm_conflicts)
    text = message.answer.call_args.args[0]

    assert "Cancelable Client" in text
    assert "Proposal Client" in text
    assert "предложение переноса" in text  # proposal block IS present
    assert text.endswith("Продолжить создание блокировки?")  # yet the message ends with only one question


@pytest.mark.asyncio
async def test_get_reason_no_cancelable_branch_never_shows_the_cancelable_footer_question():
    """Contrast case: with only a proposal-only conflict (no cancelable
    conflicts at all), the confirm_block screen must show ONLY
    _CONFIRM_BLOCK_TEXT's own question, never the cancelable-branch footer."""
    range_start, range_end = _db_range()
    proposal_only = _conflict_appointment(appointment_id=1, dt="2020-01-01 08:00", proposed_dt=range_start)
    router = _build_router(appt_repo=FakeAppointmentRepository([proposal_only]))
    get_reason = _find_message_handler(router, "get_reason")

    message = _message("Ремонт")
    state = _state(clinic_id=CLINIC_ID, staff_id=DOCTOR_ID, range_start=range_start, range_end=range_end)

    await get_reason(message, state, _admin_user())

    state.set_state.assert_awaited_once_with(SlotBlockCreationStates.confirm_block)
    text = message.answer.call_args.args[0]

    assert "Продолжить создание блокировки?" not in text
    assert "Создать блокировку с" in text


# --- get_reason / render_blocks_list: HTML escaping ---

@pytest.mark.asyncio
async def test_get_reason_confirm_block_screen_escapes_html_special_characters_in_reason():
    router = _build_router(appt_repo=FakeAppointmentRepository())
    get_reason = _find_message_handler(router, "get_reason")

    range_start, range_end = _db_range()
    message = _message("Ремонт <кабинет>")
    state = _state(clinic_id=CLINIC_ID, staff_id=DOCTOR_ID, range_start=range_start, range_end=range_end)

    await get_reason(message, state, _admin_user())

    text = message.answer.call_args.args[0]
    assert "Причина: Ремонт &lt;кабинет&gt;" in text
    assert "<кабинет>" not in text


@pytest.mark.asyncio
async def test_render_blocks_list_escapes_html_special_characters_in_reason_and_target():
    """Both the reason and the resolved doctor-name target are user-influenced
    text (reason is admin-typed, target is a doctor's full_name) and the list
    is sent with HTML parse_mode, so both must be escaped."""
    custom_admin = User(
        full_name="Петров <Врач>", phone="+998907654321", role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID, ID=DOCTOR_ID, clinic_id=CLINIC_ID, clinic_name="Зуб Мудрости",
    )
    future_start = format_datetime_for_db(get_current_tashkent_datetime() + timedelta(days=1))
    future_end = format_datetime_for_db(get_current_tashkent_datetime() + timedelta(days=1, hours=1))
    block = BlockedSlot(
        id=1, clinic_id=CLINIC_ID, staff_id=DOCTOR_ID, start_datetime=future_start, end_datetime=future_end,
        reason='Ремонт <кабинет> & "покраска"', created_by=1, created_at="2026-08-05 08:00:00",
    )
    router = create_admin_slot_blocking_router(
        FakeUserRepo(custom_admin), FakeStaffRepo(), FakeClinicRepo(),
        FakeAppointmentRepository(), FakeBlockedSlotRepository([block]),
    )
    open_manage = _find_handler(router, "open_manage")

    callback_query = _callback_query()
    state = _state()

    await open_manage(callback_query, state, custom_admin)

    text = callback_query.message.edit_text.call_args.args[0]
    assert 'Ремонт &lt;кабинет&gt; &amp; "покраска"' in text
    assert "Петров &lt;Врач&gt;" in text
    assert "<кабинет>" not in text
    assert "<Врач>" not in text
    # Guards against the target line silently falling through to the
    # unresolved-doctor fallback instead of actually resolving custom_admin's name.
    assert "Врач не найден" not in text


# --- get_reason: 4096-char overflow ladder ---
#
# The cancelable list must never be truncated (it's the admin's only warning
# before a destructive cancel-appointments action); only the proposed-datetime
# block is allowed to collapse to a count-only line, and if that's still not
# enough the handler must refuse outright rather than send a truncated
# confirmation. Both the cancelable-conflicts branch and the no-cancelable
# branch implement this independently, so each gets its own coverage.

@pytest.mark.asyncio
async def test_get_reason_under_limit_keeps_full_cancelable_and_proposed_lists():
    """Regression: well under the 4096-char budget, both lists render in full,
    uncollapsed -- the overflow ladder must not fire when it isn't needed."""
    range_start, range_end = _db_range()
    cancelable = [
        _conflict_appointment(appointment_id=i, dt=range_start, client_full_name=f"Cancelable {i}")
        for i in range(2)
    ]
    proposed_only = [
        _conflict_appointment(
            appointment_id=100 + i, dt="2020-01-01 08:00", proposed_dt=range_start,
            client_full_name=f"Proposal {i}",
        )
        for i in range(2)
    ]
    router = _build_router(appt_repo=FakeAppointmentRepository(cancelable + proposed_only))
    get_reason = _find_message_handler(router, "get_reason")

    message = _message("Ремонт")
    state = _state(clinic_id=CLINIC_ID, staff_id=DOCTOR_ID, range_start=range_start, range_end=range_end)

    await get_reason(message, state, _admin_user())

    state.set_state.assert_awaited_once_with(SlotBlockCreationStates.confirm_conflicts)
    message.answer.assert_awaited_once()
    text = message.answer.call_args.args[0]

    assert len(text) <= _TELEGRAM_MESSAGE_LIMIT
    for i in range(2):
        assert f"Cancelable {i}" in text
        assert f"Proposal {i}" in text


@pytest.mark.asyncio
async def test_get_reason_overflow_from_proposed_list_collapses_proposed_but_keeps_full_cancelable_list():
    """When the proposed-datetime block alone pushes the message over 4096
    chars, only the proposed block collapses to a count-only line -- every
    cancelable appointment line must still be present verbatim."""
    range_start, range_end = _db_range()
    cancelable = [
        _conflict_appointment(appointment_id=i, dt=range_start, client_full_name=f"Cancelable {i}")
        for i in range(3)
    ]
    proposed_only = [
        _conflict_appointment(
            appointment_id=1000 + i, dt="2020-01-01 08:00", proposed_dt=range_start,
            client_full_name=f"Proposal Client Number {i}",
        )
        for i in range(200)
    ]
    router = _build_router(appt_repo=FakeAppointmentRepository(cancelable + proposed_only))
    get_reason = _find_message_handler(router, "get_reason")

    message = _message("Ремонт")
    state = _state(clinic_id=CLINIC_ID, staff_id=DOCTOR_ID, range_start=range_start, range_end=range_end)

    await get_reason(message, state, _admin_user())

    state.set_state.assert_awaited_once_with(SlotBlockCreationStates.confirm_conflicts)
    state.clear.assert_not_called()
    message.answer.assert_awaited_once()
    text = message.answer.call_args.args[0]

    assert len(text) <= _TELEGRAM_MESSAGE_LIMIT
    for i in range(3):
        assert f"Cancelable {i}" in text
    assert "Proposal Client Number 0" not in text
    assert _PROPOSED_CONFLICTS_COUNT_ONLY_TEXT["ru"].format(count=len(proposed_only)) in text


@pytest.mark.asyncio
async def test_get_reason_overflow_survives_collapse_refuses_and_clears_state():
    """When even the cancelable list alone exceeds 4096 chars, the handler
    must refuse rather than silently truncate a destructive confirmation:
    state is cleared, the menu keyboard is shown, and no confirm state is
    ever set."""
    range_start, range_end = _db_range()
    cancelable = [
        _conflict_appointment(appointment_id=i, dt=range_start, client_full_name=f"Cancelable Client Number {i}")
        for i in range(200)
    ]
    router = _build_router(appt_repo=FakeAppointmentRepository(cancelable))
    get_reason = _find_message_handler(router, "get_reason")

    message = _message("Ремонт")
    state = _state(clinic_id=CLINIC_ID, staff_id=DOCTOR_ID, range_start=range_start, range_end=range_end)

    await get_reason(message, state, _admin_user())

    state.set_state.assert_not_called()
    state.clear.assert_awaited_once()
    message.answer.assert_awaited_once()
    text = message.answer.call_args.args[0]
    reply_markup = message.answer.call_args.kwargs["reply_markup"]

    assert text == _CANCELABLE_CONFLICTS_TOO_LONG_TEXT["ru"].format(count=len(cancelable))
    assert reply_markup == slot_blocking_menu_kb(lang="ru")


@pytest.mark.asyncio
async def test_get_reason_no_cancelable_branch_overflow_collapses_proposed_list():
    """Mirrors the cancelable-branch overflow test above, but for the
    confirm_block screen (no cancelable conflicts at all). This branch was
    missed by the first implementation pass and only fixed by a later
    review -- it needs its own regression coverage or it will regress again."""
    range_start, range_end = _db_range()
    proposed_only = [
        _conflict_appointment(
            appointment_id=1000 + i, dt="2020-01-01 08:00", proposed_dt=range_start,
            client_full_name=f"Proposal Client Number {i}",
        )
        for i in range(200)
    ]
    router = _build_router(appt_repo=FakeAppointmentRepository(proposed_only))
    get_reason = _find_message_handler(router, "get_reason")

    message = _message("Ремонт")
    state = _state(clinic_id=CLINIC_ID, staff_id=DOCTOR_ID, range_start=range_start, range_end=range_end)

    await get_reason(message, state, _admin_user())

    state.set_state.assert_awaited_once_with(SlotBlockCreationStates.confirm_block)
    state.clear.assert_not_called()
    message.answer.assert_awaited_once()
    text = message.answer.call_args.args[0]

    assert len(text) <= _TELEGRAM_MESSAGE_LIMIT
    assert "Proposal Client Number 0" not in text
    assert _PROPOSED_CONFLICTS_COUNT_ONLY_TEXT["ru"].format(count=len(proposed_only)) in text
    assert "Создать блокировку с" in text


@pytest.mark.asyncio
async def test_get_reason_cancelable_branch_telegram_bad_request_is_caught_and_menu_shown():
    """A send failure (e.g. the confirmation still somehow exceeds Telegram's
    real limits) must never escape the handler -- it falls back to the
    blocking menu with a cleared state instead of leaving the admin stuck."""
    range_start, range_end = _db_range()
    cancelable = [_conflict_appointment(appointment_id=1, dt=range_start)]
    router = _build_router(appt_repo=FakeAppointmentRepository(cancelable))
    get_reason = _find_message_handler(router, "get_reason")

    message = _message("Ремонт")
    message.answer = AsyncMock(
        side_effect=[TelegramBadRequest(method=MagicMock(), message="Bad Request: can't parse entities"), None],
    )
    state = _state(clinic_id=CLINIC_ID, staff_id=DOCTOR_ID, range_start=range_start, range_end=range_end)

    await get_reason(message, state, _admin_user())

    assert message.answer.await_count == 2
    state.clear.assert_awaited_once()
    second_call = message.answer.await_args_list[1]
    assert second_call.args[0] == _MENU_TEXT
    assert second_call.kwargs["reply_markup"] == slot_blocking_menu_kb(lang="ru")


@pytest.mark.asyncio
async def test_get_reason_no_cancelable_branch_telegram_bad_request_is_caught_and_menu_shown():
    """Same TelegramBadRequest guard as above, for the confirm_block (no
    cancelable conflicts) send -- this branch has its own separate
    try/except and must be verified independently."""
    range_start, range_end = _db_range()
    router = _build_router(appt_repo=FakeAppointmentRepository())
    get_reason = _find_message_handler(router, "get_reason")

    message = _message("Ремонт")
    message.answer = AsyncMock(
        side_effect=[TelegramBadRequest(method=MagicMock(), message="Bad Request: can't parse entities"), None],
    )
    state = _state(clinic_id=CLINIC_ID, staff_id=DOCTOR_ID, range_start=range_start, range_end=range_end)

    await get_reason(message, state, _admin_user())

    assert message.answer.await_count == 2
    state.clear.assert_awaited_once()
    second_call = message.answer.await_args_list[1]
    assert second_call.args[0] == _MENU_TEXT
    assert second_call.kwargs["reply_markup"] == slot_blocking_menu_kb(lang="ru")


# --- get_reason: blank-line separator before the proposed-conflicts block ---

@pytest.mark.asyncio
async def test_get_reason_cancelable_branch_has_blank_line_separator_before_proposed_block():
    range_start, range_end = _db_range()
    cancelable = _conflict_appointment(appointment_id=1, dt=range_start, client_full_name="Cancelable Client")
    proposal_only = _conflict_appointment(
        appointment_id=2, dt="2020-01-01 08:00", proposed_dt=range_start, client_full_name="Proposal Client",
    )
    router = _build_router(appt_repo=FakeAppointmentRepository([cancelable, proposal_only]))
    get_reason = _find_message_handler(router, "get_reason")

    message = _message("Ремонт")
    state = _state(clinic_id=CLINIC_ID, staff_id=DOCTOR_ID, range_start=range_start, range_end=range_end)

    await get_reason(message, state, _admin_user())

    text = message.answer.call_args.args[0]
    assert "\n\nℹ️" in text


@pytest.mark.asyncio
async def test_get_reason_no_cancelable_branch_has_blank_line_separator_before_proposed_block():
    range_start, range_end = _db_range()
    proposal_only = _conflict_appointment(appointment_id=1, dt="2020-01-01 08:00", proposed_dt=range_start)
    router = _build_router(appt_repo=FakeAppointmentRepository([proposal_only]))
    get_reason = _find_message_handler(router, "get_reason")

    message = _message("Ремонт")
    state = _state(clinic_id=CLINIC_ID, staff_id=DOCTOR_ID, range_start=range_start, range_end=range_end)

    await get_reason(message, state, _admin_user())

    text = message.answer.call_args.args[0]
    assert "\n\nℹ️" in text
