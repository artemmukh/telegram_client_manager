from datetime import timedelta

import pytest

from bot.exceptions.blocked_slot_exceptions import (
    BlockedSlotAlreadyCancelledError,
    BlockedSlotNotFoundError,
    InvalidBlockRangeError,
    InvalidBlockReasonError,
)
from bot.exceptions.user_exceptions import (
    ReplyMenuButtonInputError,
    RoleError,
    UserNotFoundError,
)
from bot.models.appointment import Appointment
from bot.models.blocked_slot import BlockedSlot
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.services.appointment.slot_blocking import SlotBlockingService
from bot.services.utils.date_parser import format_datetime_for_db, get_current_tashkent_datetime
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.reply_menu_labels import ADMIN_MENU_LABELS, REPLY_MENU_TEXT_MESSAGE
from bot.utils.role import Role
from bot.validators.validators import _INVALID_PURPOSE_MESSAGE
from tests.conftest import FakeBlockedSlotRepository


class FakeAppointmentRepository:
    def __init__(self, appointments=None):
        self.appointments = list(appointments or [])
        self.status_updates: list[tuple[int, AppointmentStatus]] = []

    async def get_appointments_in_range(self, clinic_id, doctor_id, start_datetime, end_datetime):
        return [
            a for a in self.appointments
            if a.clinic_id == clinic_id
            and (doctor_id is None or a.doctor_id == doctor_id)
            and start_datetime <= a.datetime < end_datetime
        ]

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.status_updates.append((appointment_id, status))


class FakeUserRepository:
    def __init__(self, admin_by_telegram_id=None):
        self.admin_by_telegram_id = dict(admin_by_telegram_id or {})

    async def get_user_by_telegram_id(self, telegram_user_id):
        return self.admin_by_telegram_id.get(telegram_user_id)


class FakeStaffRepository:
    def __init__(self, staff_by_telegram_id=None):
        self.staff_by_telegram_id = dict(staff_by_telegram_id or {})

    async def get_staff(self, telegram_user_id):
        return self.staff_by_telegram_id.get(telegram_user_id)


class FakeClinicRepository:
    def __init__(self, clinic_by_id=None):
        self.clinic_by_id = dict(clinic_by_id or {})

    async def get_clinic_by_id(self, clinic_id):
        return self.clinic_by_id.get(clinic_id)


class RaisingBlockedSlotRepository(FakeBlockedSlotRepository):
    async def create_block(self, block):
        raise RuntimeError("create_block failed")


_DEFAULT_ADMIN_TELEGRAM_ID = 999
_DEFAULT_CLINIC_ID = 1


def _service(
    blocked_slot_repo=None, appointment_repo=None, user_repo=None, staff_repo=None, clinic_repo=None,
):
    return SlotBlockingService(
        blocked_slot_repo or FakeBlockedSlotRepository(),
        appointment_repo or FakeAppointmentRepository(),
        user_repo or FakeUserRepository(),
        staff_repository=staff_repo or FakeStaffRepository({
            _DEFAULT_ADMIN_TELEGRAM_ID: Staff(
                telegram_user_id=_DEFAULT_ADMIN_TELEGRAM_ID, clinic_id=_DEFAULT_CLINIC_ID,
                visibility_scope="clinic",
            ),
        }),
        clinic_repository=clinic_repo or FakeClinicRepository({
            _DEFAULT_CLINIC_ID: Clinic(name="Clinic 1", token="clinic-1", clinic_id=_DEFAULT_CLINIC_ID),
        }),
    )


def _future_range(start_offset_days=2, duration_minutes=60, hour=10, minute=0):
    start_dt = get_current_tashkent_datetime().replace(
        hour=hour, minute=minute, second=0, microsecond=0,
    ) + timedelta(days=start_offset_days)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    return start_dt.strftime("%d.%m.%Y %H:%M"), end_dt.strftime("%d.%m.%Y %H:%M")


def _future_db_datetime(hour, minute, start_offset_days=2):
    """The same day _future_range() lands on, at another time, in DB format --
    for placing an appointment relative to a to-be-created block."""
    dt = get_current_tashkent_datetime().replace(
        hour=hour, minute=minute, second=0, microsecond=0,
    ) + timedelta(days=start_offset_days)
    return format_datetime_for_db(dt)


def _admin(telegram_user_id=999, admin_id=42):
    return User(
        full_name="Petrov Petr", phone="+998907654321", role=Role.ADMIN,
        telegram_user_id=telegram_user_id, ID=admin_id,
    )


def _appointment(appointment_id=1, doctor_id=42, clinic_id=1, dt="2026-08-07 10:00", status=AppointmentStatus.PENDING):
    return Appointment(
        clinic_id=clinic_id, client_id=7, doctor_id=doctor_id, datetime=dt, purpose="Consultation",
        created_by=CreatedBy.CLIENT, status=status, id=appointment_id,
    )


def _block(
    block_id=1, clinic_id=1, staff_id=42, start="2026-08-07 09:00", end="2026-08-07 11:00",
    reason="Vacation", created_by=1, cancelled_at=None,
):
    return BlockedSlot(
        id=block_id, clinic_id=clinic_id, staff_id=staff_id, start_datetime=start, end_datetime=end,
        reason=reason, created_by=created_by, created_at="2026-08-05 08:00:00", cancelled_at=cancelled_at,
    )


# --- validate_range ---

@pytest.mark.asyncio
async def test_validate_range_parses_correct_range():
    service = _service()
    start_raw, end_raw = _future_range()

    start, end = await service.validate_range(start_raw, end_raw)

    assert start < end
    expected_start = format_datetime_for_db(
        get_current_tashkent_datetime().replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=2)
    )
    assert start == expected_start


@pytest.mark.asyncio
async def test_validate_range_rejects_end_before_start():
    service = _service()
    start_raw, _ = _future_range()
    day = (get_current_tashkent_datetime() + timedelta(days=2)).strftime("%d.%m.%Y")
    earlier_end_raw = f"{day} 09:00"

    with pytest.raises(InvalidBlockRangeError):
        await service.validate_range(start_raw, earlier_end_raw)


@pytest.mark.asyncio
async def test_validate_range_rejects_end_equal_to_start():
    service = _service()
    start_raw, _ = _future_range()

    with pytest.raises(InvalidBlockRangeError):
        await service.validate_range(start_raw, start_raw)


@pytest.mark.asyncio
async def test_validate_range_rejects_fully_past_range():
    service = _service()
    past_day = (get_current_tashkent_datetime() - timedelta(days=1)).strftime("%d.%m.%Y")
    start_raw = f"{past_day} 10:00"
    end_raw = f"{past_day} 11:00"

    with pytest.raises(InvalidBlockRangeError):
        await service.validate_range(start_raw, end_raw)


@pytest.mark.asyncio
async def test_validate_range_accepts_range_that_started_in_the_past_but_ends_in_the_future():
    """The "doctor just went home sick" case: blocking must be allowed to start
    in the past as long as the interval is not fully behind us."""
    service = _service()
    yesterday = (get_current_tashkent_datetime() - timedelta(days=1)).strftime("%d.%m.%Y")
    tomorrow = (get_current_tashkent_datetime() + timedelta(days=1)).strftime("%d.%m.%Y")

    start, end = await service.validate_range(f"{yesterday} 10:00", f"{tomorrow} 10:00")

    assert start < end
    assert start < format_datetime_for_db(get_current_tashkent_datetime()) < end


@pytest.mark.asyncio
async def test_validate_range_rejects_unparseable_input():
    service = _service()

    with pytest.raises(InvalidBlockRangeError):
        await service.validate_range("not a date", "also not a date")


# --- find_conflicts ---

@pytest.mark.asyncio
async def test_find_conflicts_finds_doctors_own_appointment_in_range():
    appointment = _appointment(doctor_id=42, dt="2026-08-07 10:00")
    service = _service(appointment_repo=FakeAppointmentRepository([appointment]))

    conflicts = await service.find_conflicts(1, 42, "2026-08-07 09:00", "2026-08-07 11:00")

    assert conflicts == [appointment]


@pytest.mark.asyncio
async def test_find_conflicts_finds_confirmed_and_pending_statuses():
    pending = _appointment(appointment_id=1, doctor_id=42, dt="2026-08-07 10:00", status=AppointmentStatus.PENDING)
    confirmed = _appointment(appointment_id=2, doctor_id=42, dt="2026-08-07 10:30", status=AppointmentStatus.CONFIRMED)
    service = _service(appointment_repo=FakeAppointmentRepository([pending, confirmed]))

    conflicts = await service.find_conflicts(1, 42, "2026-08-07 09:00", "2026-08-07 11:00")

    assert conflicts == [pending, confirmed]


@pytest.mark.asyncio
async def test_find_conflicts_clinic_wide_finds_all_doctors_appointments():
    doctor_a = _appointment(appointment_id=1, doctor_id=42, dt="2026-08-07 10:00")
    doctor_b = _appointment(appointment_id=2, doctor_id=99, dt="2026-08-07 10:15")
    service = _service(appointment_repo=FakeAppointmentRepository([doctor_a, doctor_b]))

    conflicts = await service.find_conflicts(1, None, "2026-08-07 09:00", "2026-08-07 11:00")

    assert conflicts == [doctor_a, doctor_b]


@pytest.mark.asyncio
async def test_find_conflicts_excludes_appointments_outside_range():
    outside = _appointment(doctor_id=42, dt="2026-08-07 12:00")
    service = _service(appointment_repo=FakeAppointmentRepository([outside]))

    conflicts = await service.find_conflicts(1, 42, "2026-08-07 09:00", "2026-08-07 11:00")

    assert conflicts == []


# --- find_conflicts: appointment duration vs block boundaries ---
#
# An appointment occupies [datetime, +SLOT_STEP_MINUTES), so a block starting
# after the appointment's start instant can still collide with it. The step is
# bound by name inside slot_blocking (patching bot.config.booking_config would
# not reach the already-imported name, and the sibling binding inside
# appointment_management is a separate name), so it is patched on this module
# only. Nothing on this path reads BOOKING_SLOTS, so the slot grid stays out of
# these tests entirely.

@pytest.mark.asyncio
async def test_find_conflicts_finds_appointment_starting_before_the_block(monkeypatch):
    """Step 60: a 14:00 appointment occupies [14:00, 15:00) and collides with a
    14:30-15:00 block, even though 14:00 is outside the block range."""
    monkeypatch.setattr("bot.services.appointment.slot_blocking.SLOT_STEP_MINUTES", 60)
    appointment = _appointment(doctor_id=42, dt="2026-08-07 14:00")
    service = _service(appointment_repo=FakeAppointmentRepository([appointment]))

    conflicts = await service.find_conflicts(1, 42, "2026-08-07 14:30", "2026-08-07 15:00")

    assert conflicts == [appointment]


@pytest.mark.asyncio
async def test_find_conflicts_excludes_appointment_starting_exactly_at_the_block_end(monkeypatch):
    """A 15:00 appointment starts where the block ends -- half-open ranges do
    not collide."""
    monkeypatch.setattr("bot.services.appointment.slot_blocking.SLOT_STEP_MINUTES", 60)
    appointment = _appointment(doctor_id=42, dt="2026-08-07 15:00")
    service = _service(appointment_repo=FakeAppointmentRepository([appointment]))

    conflicts = await service.find_conflicts(1, 42, "2026-08-07 14:30", "2026-08-07 15:00")

    assert conflicts == []


@pytest.mark.asyncio
async def test_find_conflicts_excludes_appointment_ending_exactly_at_the_block_start(monkeypatch):
    """Back-to-back: a 13:00 appointment occupies [13:00, 14:00) and merely
    touches a 14:00-14:30 block. It falls inside the widened candidate window
    (which reaches back one slot step) and must be dropped by the exact
    post-filter."""
    monkeypatch.setattr("bot.services.appointment.slot_blocking.SLOT_STEP_MINUTES", 60)
    appointment = _appointment(doctor_id=42, dt="2026-08-07 13:00")
    appointment_repo = FakeAppointmentRepository([appointment])
    service = _service(appointment_repo=appointment_repo)

    conflicts = await service.find_conflicts(1, 42, "2026-08-07 14:00", "2026-08-07 14:30")

    # The widened candidate query does reach this appointment -- so the empty
    # result comes from the post-filter, not from the appointment being unseen.
    candidates = await appointment_repo.get_appointments_in_range(
        1, 42, "2026-08-07 13:00", "2026-08-07 14:30",
    )
    assert candidates == [appointment]
    assert conflicts == []


# --- create_block ---

@pytest.mark.asyncio
async def test_create_block_succeeds_without_conflicts():
    admin = _admin()
    blocked_slot_repo = FakeBlockedSlotRepository()
    service = _service(
        blocked_slot_repo=blocked_slot_repo,
        user_repo=FakeUserRepository({admin.telegram_user_id: admin}),
    )
    start_raw, end_raw = _future_range()

    block, cancelled = await service.create_block(
        admin.telegram_user_id, clinic_id=1, staff_id=42, start_raw=start_raw, end_raw=end_raw, reason="Vacation",
    )

    assert block.id is not None
    assert block.clinic_id == 1
    assert block.staff_id == 42
    assert block.reason == "Vacation"
    assert block.created_by == admin.ID
    assert cancelled == []
    assert blocked_slot_repo.blocks == [block]


@pytest.mark.asyncio
async def test_create_block_cancels_only_pending_and_confirmed_conflicts():
    admin = _admin()
    start_raw, end_raw = _future_range()
    start, end = await _service().validate_range(start_raw, end_raw)

    pending = _appointment(appointment_id=1, doctor_id=42, dt=start, status=AppointmentStatus.PENDING)
    confirmed = _appointment(appointment_id=2, doctor_id=42, dt=start, status=AppointmentStatus.CONFIRMED)
    completed = _appointment(appointment_id=3, doctor_id=42, dt=start, status=AppointmentStatus.COMPLETED)
    already_cancelled = _appointment(appointment_id=4, doctor_id=42, dt=start, status=AppointmentStatus.CANCELLED)
    no_show = _appointment(appointment_id=5, doctor_id=42, dt=start, status=AppointmentStatus.NO_SHOW)
    expired = _appointment(appointment_id=6, doctor_id=42, dt=start, status=AppointmentStatus.EXPIRED)

    appt_repo = FakeAppointmentRepository(
        [pending, confirmed, completed, already_cancelled, no_show, expired]
    )
    service = _service(
        appointment_repo=appt_repo,
        user_repo=FakeUserRepository({admin.telegram_user_id: admin}),
    )

    block, cancelled = await service.create_block(
        admin.telegram_user_id, clinic_id=1, staff_id=42, start_raw=start_raw, end_raw=end_raw, reason="Repair",
    )

    assert {a.id for a in cancelled} == {1, 2}
    assert pending.status == AppointmentStatus.CANCELLED
    assert confirmed.status == AppointmentStatus.CANCELLED
    assert completed.status == AppointmentStatus.COMPLETED
    assert already_cancelled.status == AppointmentStatus.CANCELLED
    assert no_show.status == AppointmentStatus.NO_SHOW
    assert expired.status == AppointmentStatus.EXPIRED
    assert {aid for aid, _ in appt_repo.status_updates} == {1, 2}


@pytest.mark.asyncio
async def test_create_block_raises_when_admin_not_found():
    start_raw, end_raw = _future_range()
    service = _service(user_repo=FakeUserRepository({}))

    with pytest.raises(UserNotFoundError):
        await service.create_block(
            999, clinic_id=1, staff_id=42, start_raw=start_raw, end_raw=end_raw, reason="Vacation",
        )


@pytest.mark.asyncio
async def test_create_block_cancels_appointment_whose_duration_runs_into_the_block(monkeypatch):
    """End-to-end counterpart of the find_conflicts duration tests: a 14:00
    appointment is cancelled by a 14:30-15:00 block under a 60-minute step."""
    monkeypatch.setattr("bot.services.appointment.slot_blocking.SLOT_STEP_MINUTES", 60)
    admin = _admin()
    start_raw, end_raw = _future_range(duration_minutes=30, hour=14, minute=30)
    earlier = _appointment(
        appointment_id=1, doctor_id=42, dt=_future_db_datetime(14, 0), status=AppointmentStatus.CONFIRMED,
    )
    appt_repo = FakeAppointmentRepository([earlier])
    service = _service(
        appointment_repo=appt_repo,
        user_repo=FakeUserRepository({admin.telegram_user_id: admin}),
    )

    block, cancelled = await service.create_block(
        admin.telegram_user_id, clinic_id=1, staff_id=42, start_raw=start_raw, end_raw=end_raw, reason="Планёрка",
    )

    assert block.start_datetime == _future_db_datetime(14, 30)
    assert cancelled == [earlier]
    assert earlier.status == AppointmentStatus.CANCELLED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CANCELLED)]


@pytest.mark.asyncio
async def test_create_block_leaves_back_to_back_appointment_untouched(monkeypatch):
    """A 13:00 appointment ends exactly where a 14:00-14:30 block starts."""
    monkeypatch.setattr("bot.services.appointment.slot_blocking.SLOT_STEP_MINUTES", 60)
    admin = _admin()
    start_raw, end_raw = _future_range(duration_minutes=30, hour=14, minute=0)
    earlier = _appointment(
        appointment_id=1, doctor_id=42, dt=_future_db_datetime(13, 0), status=AppointmentStatus.CONFIRMED,
    )
    appt_repo = FakeAppointmentRepository([earlier])
    service = _service(
        appointment_repo=appt_repo,
        user_repo=FakeUserRepository({admin.telegram_user_id: admin}),
    )

    _, cancelled = await service.create_block(
        admin.telegram_user_id, clinic_id=1, staff_id=42, start_raw=start_raw, end_raw=end_raw, reason="Планёрка",
    )

    assert cancelled == []
    assert earlier.status == AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_create_block_propagates_invalid_range():
    admin = _admin()
    service = _service(user_repo=FakeUserRepository({admin.telegram_user_id: admin}))
    day = (get_current_tashkent_datetime() + timedelta(days=2)).strftime("%d.%m.%Y")

    with pytest.raises(InvalidBlockRangeError):
        await service.create_block(
            admin.telegram_user_id, clinic_id=1, staff_id=42,
            start_raw=f"{day} 11:00", end_raw=f"{day} 10:00", reason="Vacation",
        )


# --- validate_reason ---

def test_validate_reason_returns_stripped_reason():
    assert _service().validate_reason("  Отпуск  ") == "Отпуск"


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["A", "A" * 101])
async def test_create_block_rejects_reason_outside_length_bounds(reason):
    admin = _admin()
    service = _service(user_repo=FakeUserRepository({admin.telegram_user_id: admin}))
    start_raw, end_raw = _future_range()

    with pytest.raises(InvalidBlockReasonError) as exc_info:
        await service.create_block(
            admin.telegram_user_id, clinic_id=1, staff_id=42,
            start_raw=start_raw, end_raw=end_raw, reason=reason,
        )

    # The underlying validator is validate_purpose, but its "describe the
    # service" wording makes no sense for a block reason -- the message must be
    # the blocking-specific one.
    message = str(exc_info.value)
    assert message != _INVALID_PURPOSE_MESSAGE["ru"]
    assert "услугу" not in message
    assert "блокировки" in message


@pytest.mark.asyncio
async def test_create_block_validates_reason_before_the_range():
    """Reason is checked first, so a request that is wrong in both ways reports
    the reason, not the range."""
    admin = _admin()
    service = _service(user_repo=FakeUserRepository({admin.telegram_user_id: admin}))
    past_day = (get_current_tashkent_datetime() - timedelta(days=1)).strftime("%d.%m.%Y")

    with pytest.raises(InvalidBlockReasonError):
        await service.create_block(
            admin.telegram_user_id, clinic_id=1, staff_id=42,
            start_raw=f"{past_day} 10:00", end_raw=f"{past_day} 11:00", reason="A",
        )


@pytest.mark.asyncio
async def test_create_block_propagates_reply_menu_button_input_unchanged():
    """Tapping a persistent menu button instead of typing a reason must keep its
    own "you pressed a menu button" message rather than being flattened into the
    generic invalid-reason error."""
    admin = _admin()
    service = _service(user_repo=FakeUserRepository({admin.telegram_user_id: admin}))
    start_raw, end_raw = _future_range()

    with pytest.raises(ReplyMenuButtonInputError) as exc_info:
        await service.create_block(
            admin.telegram_user_id, clinic_id=1, staff_id=42,
            start_raw=start_raw, end_raw=end_raw, reason=ADMIN_MENU_LABELS["ru"]["records"],
        )

    assert not isinstance(exc_info.value, InvalidBlockReasonError)
    assert str(exc_info.value) == REPLY_MENU_TEXT_MESSAGE["ru"]


# --- list_active_blocks ---

@pytest.mark.asyncio
async def test_list_active_blocks_returns_active_future_blocks():
    future_start = format_datetime_for_db(get_current_tashkent_datetime() + timedelta(days=1))
    future_end = format_datetime_for_db(get_current_tashkent_datetime() + timedelta(days=1, hours=1))
    active_block = _block(block_id=1, start=future_start, end=future_end)
    blocked_slot_repo = FakeBlockedSlotRepository([active_block])
    service = _service(blocked_slot_repo=blocked_slot_repo)

    blocks = await service.list_active_blocks(clinic_id=1)

    assert blocks == [active_block]


@pytest.mark.asyncio
async def test_list_active_blocks_excludes_cancelled_blocks():
    future_start = format_datetime_for_db(get_current_tashkent_datetime() + timedelta(days=1))
    future_end = format_datetime_for_db(get_current_tashkent_datetime() + timedelta(days=1, hours=1))
    cancelled_block = _block(
        block_id=1, start=future_start, end=future_end, cancelled_at="2026-08-05 08:00:00",
    )
    blocked_slot_repo = FakeBlockedSlotRepository([cancelled_block])
    service = _service(blocked_slot_repo=blocked_slot_repo)

    blocks = await service.list_active_blocks(clinic_id=1)

    assert blocks == []


@pytest.mark.asyncio
async def test_list_active_blocks_excludes_expired_blocks():
    past_start = format_datetime_for_db(get_current_tashkent_datetime() - timedelta(days=2))
    past_end = format_datetime_for_db(get_current_tashkent_datetime() - timedelta(days=1))
    expired_block = _block(block_id=1, start=past_start, end=past_end)
    blocked_slot_repo = FakeBlockedSlotRepository([expired_block])
    service = _service(blocked_slot_repo=blocked_slot_repo)

    blocks = await service.list_active_blocks(clinic_id=1)

    assert blocks == []


# --- cancel_block ---

@pytest.mark.asyncio
async def test_cancel_block_succeeds():
    block = _block(block_id=1, cancelled_at=None)
    blocked_slot_repo = FakeBlockedSlotRepository([block])
    service = _service(blocked_slot_repo=blocked_slot_repo)

    result = await service.cancel_block(999, block_id=1)

    assert result.cancelled_at is not None
    assert blocked_slot_repo.blocks[0].cancelled_at is not None


@pytest.mark.asyncio
async def test_cancel_block_raises_when_already_cancelled():
    block = _block(block_id=1, cancelled_at="2026-08-05 08:00:00")
    blocked_slot_repo = FakeBlockedSlotRepository([block])
    service = _service(blocked_slot_repo=blocked_slot_repo)

    with pytest.raises(BlockedSlotAlreadyCancelledError):
        await service.cancel_block(999, block_id=1)


@pytest.mark.asyncio
async def test_cancel_block_raises_when_not_found():
    service = _service(blocked_slot_repo=FakeBlockedSlotRepository())

    with pytest.raises(BlockedSlotNotFoundError):
        await service.cancel_block(999, block_id=404)


@pytest.mark.asyncio
async def test_cancel_block_raises_not_found_for_block_in_other_clinic():
    block = _block(block_id=1, clinic_id=2, cancelled_at=None)
    blocked_slot_repo = FakeBlockedSlotRepository([block])
    admin_telegram_id = 111
    staff_repo = FakeStaffRepository({
        admin_telegram_id: Staff(telegram_user_id=admin_telegram_id, clinic_id=1, visibility_scope="clinic"),
    })
    clinic_repo = FakeClinicRepository({1: Clinic(name="Clinic 1", token="c1", clinic_id=1)})
    service = _service(blocked_slot_repo=blocked_slot_repo, staff_repo=staff_repo, clinic_repo=clinic_repo)

    with pytest.raises(BlockedSlotNotFoundError):
        await service.cancel_block(admin_telegram_id, block_id=1)

    assert blocked_slot_repo.blocks[0].cancelled_at is None


@pytest.mark.asyncio
async def test_cancel_block_raises_not_found_for_other_doctors_block():
    other_doctor_id = 77
    acting_doctor = _admin(telegram_user_id=222, admin_id=88)
    block = _block(block_id=1, clinic_id=1, staff_id=other_doctor_id, cancelled_at=None)
    blocked_slot_repo = FakeBlockedSlotRepository([block])
    staff_repo = FakeStaffRepository({
        acting_doctor.telegram_user_id: Staff(
            telegram_user_id=acting_doctor.telegram_user_id, clinic_id=1, visibility_scope="own",
        ),
    })
    clinic_repo = FakeClinicRepository({1: Clinic(name="Clinic 1", token="c1", clinic_id=1)})
    service = _service(
        blocked_slot_repo=blocked_slot_repo,
        user_repo=FakeUserRepository({acting_doctor.telegram_user_id: acting_doctor}),
        staff_repo=staff_repo,
        clinic_repo=clinic_repo,
    )

    with pytest.raises(BlockedSlotNotFoundError):
        await service.cancel_block(acting_doctor.telegram_user_id, block_id=1)

    assert blocked_slot_repo.blocks[0].cancelled_at is None


@pytest.mark.asyncio
async def test_cancel_block_allows_doctor_to_cancel_own_block():
    acting_doctor = _admin(telegram_user_id=222, admin_id=88)
    block = _block(block_id=1, clinic_id=1, staff_id=acting_doctor.ID, cancelled_at=None)
    blocked_slot_repo = FakeBlockedSlotRepository([block])
    staff_repo = FakeStaffRepository({
        acting_doctor.telegram_user_id: Staff(
            telegram_user_id=acting_doctor.telegram_user_id, clinic_id=1, visibility_scope="own",
        ),
    })
    clinic_repo = FakeClinicRepository({1: Clinic(name="Clinic 1", token="c1", clinic_id=1)})
    service = _service(
        blocked_slot_repo=blocked_slot_repo,
        user_repo=FakeUserRepository({acting_doctor.telegram_user_id: acting_doctor}),
        staff_repo=staff_repo,
        clinic_repo=clinic_repo,
    )

    result = await service.cancel_block(acting_doctor.telegram_user_id, block_id=1)

    assert result.cancelled_at is not None


@pytest.mark.asyncio
async def test_cancel_block_raises_not_found_for_clinic_wide_block_when_acting_as_own_scope_doctor():
    acting_doctor = _admin(telegram_user_id=222, admin_id=88)
    block = _block(block_id=1, clinic_id=1, staff_id=None, cancelled_at=None)
    blocked_slot_repo = FakeBlockedSlotRepository([block])
    staff_repo = FakeStaffRepository({
        acting_doctor.telegram_user_id: Staff(
            telegram_user_id=acting_doctor.telegram_user_id, clinic_id=1, visibility_scope="own",
        ),
    })
    clinic_repo = FakeClinicRepository({1: Clinic(name="Clinic 1", token="c1", clinic_id=1)})
    service = _service(
        blocked_slot_repo=blocked_slot_repo,
        user_repo=FakeUserRepository({acting_doctor.telegram_user_id: acting_doctor}),
        staff_repo=staff_repo,
        clinic_repo=clinic_repo,
    )

    with pytest.raises(BlockedSlotNotFoundError):
        await service.cancel_block(acting_doctor.telegram_user_id, block_id=1)

    assert blocked_slot_repo.blocks[0].cancelled_at is None


@pytest.mark.asyncio
async def test_cancel_block_allows_clinic_admin_to_cancel_any_doctors_block():
    block = _block(block_id=1, clinic_id=1, staff_id=555, cancelled_at=None)
    blocked_slot_repo = FakeBlockedSlotRepository([block])

    service = _service(blocked_slot_repo=blocked_slot_repo)

    result = await service.cancel_block(_DEFAULT_ADMIN_TELEGRAM_ID, block_id=1)

    assert result.cancelled_at is not None


@pytest.mark.asyncio
async def test_cancel_block_raises_role_error_when_acting_user_not_staff():
    block = _block(block_id=1, clinic_id=1, cancelled_at=None)
    blocked_slot_repo = FakeBlockedSlotRepository([block])
    service = _service(blocked_slot_repo=blocked_slot_repo, staff_repo=FakeStaffRepository({}))

    with pytest.raises(RoleError):
        await service.cancel_block(12345, block_id=1)


# --- find_cancelable_conflicts ---

@pytest.mark.asyncio
async def test_find_cancelable_conflicts_filters_out_non_cancelable_statuses():
    pending = _appointment(appointment_id=1, doctor_id=42, dt="2026-08-07 10:00", status=AppointmentStatus.PENDING)
    completed = _appointment(appointment_id=2, doctor_id=42, dt="2026-08-07 10:00", status=AppointmentStatus.COMPLETED)
    service = _service(appointment_repo=FakeAppointmentRepository([pending, completed]))

    cancelable = await service.find_cancelable_conflicts(1, 42, "2026-08-07 09:00", "2026-08-07 11:00")

    assert cancelable == [pending]


# --- create_block ordering ---

@pytest.mark.asyncio
async def test_create_block_does_not_cancel_appointments_when_block_insert_fails():
    admin = _admin()
    start_raw, end_raw = _future_range()
    start, end = await _service().validate_range(start_raw, end_raw)
    pending = _appointment(appointment_id=1, doctor_id=42, dt=start, status=AppointmentStatus.PENDING)
    appt_repo = FakeAppointmentRepository([pending])
    service = _service(
        blocked_slot_repo=RaisingBlockedSlotRepository(),
        appointment_repo=appt_repo,
        user_repo=FakeUserRepository({admin.telegram_user_id: admin}),
    )

    with pytest.raises(RuntimeError):
        await service.create_block(
            admin.telegram_user_id, clinic_id=1, staff_id=42, start_raw=start_raw, end_raw=end_raw, reason="Vacation",
        )

    assert appt_repo.status_updates == []
    assert pending.status == AppointmentStatus.PENDING
