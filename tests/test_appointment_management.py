from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest

from bot.exceptions.appointment_exceptions import (
    AppointmentAlreadyFinalizedError,
    AppointmentNotFoundError,
    AwaitingClinicDecisionError,
    BookingTooSoonError,
    CancellationWindowExpiredError,
    NegotiationInProgressError,
    NoPendingProposalError,
    PendingRequestLimitExceededError,
    SlotUnavailableError,
)
from bot.exceptions.user_exceptions import RoleError, UserNotFoundError
from bot.models.appointment import Appointment
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.utils.date_parser import get_current_tashkent_datetime
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


class FakeAppointmentRepository:
    def __init__(self, appointments=None):
        self.appointments = list(appointments or [])
        self.created = []
        self.status_updates = []
        self.updated = []
        self.proposed_datetime_updates = []
        self.proposed_by_updates = []
        self.price_updates = []

    async def create_appointment(self, appointment):
        self.created.append(appointment)
        return appointment

    async def get_appointments_by_client_id(self, client_id, clinic_id=None, doctor_id=None):
        return [a for a in self.appointments if a.client_id == client_id]

    async def get_appointment_by_id(self, appointment_id):
        return next((a for a in self.appointments if a.id == appointment_id), None)

    async def get_appointments_by_doctor_and_date(self, doctor_id, date):
        return [
            a for a in self.appointments
            if a.doctor_id == doctor_id and a.datetime.startswith(date) and a.status == AppointmentStatus.CONFIRMED
        ]

    async def appointment_exists(self, appointment_id):
        return any(a.id == appointment_id for a in self.appointments)

    async def delete_appointment(self, appointment_id):
        self.appointments = [a for a in self.appointments if a.id != appointment_id]

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.status_updates.append((appointment_id, status))

    async def update_appointment(self, appointment_id, appointment):
        self.updated.append((appointment_id, appointment))

    async def update_appointment_price(self, appointment_id, price):
        self.price_updates.append((appointment_id, price))

    async def update_proposed_datetime(self, appointment_id, proposed_datetime):
        self.proposed_datetime_updates.append((appointment_id, proposed_datetime))

    async def update_proposed_by(self, appointment_id, proposed_by):
        self.proposed_by_updates.append((appointment_id, proposed_by))

    async def get_appointments_by_telegram_id(self, telegram_user_id):
        return list(self.appointments)


class FakeUserRepo:
    def __init__(self, client=None, admin=None, staff_by_clinic=None, users_by_id=None):
        self.client = client
        self.admin = admin
        self.staff_by_clinic = staff_by_clinic or {}
        self.users_by_id = users_by_id or {}

    async def get_client_by_phone(self, phone):
        if self.client and self.client.phone == phone:
            return self.client
        return None

    async def get_client_by_id(self, client_id):
        if self.client and self.client.ID == client_id:
            return self.client
        return None

    async def get_user_by_telegram_id(self, telegram_user_id):
        if self.admin and self.admin.telegram_user_id == telegram_user_id:
            return self.admin
        if self.client and self.client.telegram_user_id == telegram_user_id:
            return self.client
        return None

    async def get_staff_users_by_clinic_id(self, clinic_id):
        return self.staff_by_clinic.get(clinic_id, [])

    async def get_user_by_id(self, user_id):
        return self.users_by_id.get(user_id)


class FakeStaffRepo:
    def __init__(self, staff=None):
        self.staff = staff

    async def get_staff(self, telegram_user_id):
        return self.staff


class FakeClinicRepo:
    def __init__(self, clinic=None):
        self.clinic = clinic

    async def get_clinic_by_id(self, clinic_id):
        return self.clinic


def _clinic_repo(clinic_id=1):
    return FakeClinicRepo(Clinic(clinic_id=clinic_id, name="Зуб Мудрости", token="t"))


def _client():
    return User(full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, ID=7)


def _future_datetime(days: int = 2, time_str: str = "14:30") -> str:
    """A datetime string safely beyond the 2h30 minimum lead time, for tests that
    just need a valid, parseable future date regardless of when the suite runs."""
    day = (get_current_tashkent_datetime() + timedelta(days=days)).strftime("%Y-%m-%d")
    return f"{day} {time_str}"


def _appointment(appointment_id=1, client_id=7):
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        datetime="2026-07-10 14:30",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        id=appointment_id,
    )


@pytest.mark.asyncio
async def test_create_appointment_resolves_clinic_and_client():
    appt_repo = FakeAppointmentRepository()
    admin = User(full_name="Доктор", phone="+998900000000", role=Role.ADMIN, ID=42, telegram_user_id=999)
    service = AppointmentManagement(
        appt_repo,
        FakeUserRepo(_client(), admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1)),
        _clinic_repo(),
    )

    appointment = await service.create_appointment(
        999,
        {"phone": "+998901234567", "appointment_datetime": _future_datetime(), "purpose": "Консультация"},
    )

    assert appt_repo.created == [appointment]
    assert appointment.clinic_id == 1
    assert appointment.client_id == 7
    assert appointment.doctor_id == 42
    assert appointment.clinic_name == "Зуб Мудрости"
    assert appointment.status is AppointmentStatus.PENDING
    assert appointment.created_by is CreatedBy.ADMIN


@pytest.mark.asyncio
async def test_create_appointment_raises_when_admin_not_found():
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(_client()),
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1)),
        _clinic_repo(),
    )

    with pytest.raises(UserNotFoundError):
        await service.create_appointment(
            999,
            {"phone": "+998901234567", "appointment_datetime": "2026-07-10 14:30", "purpose": "Консультация"},
        )


@pytest.mark.asyncio
async def test_create_appointment_rejects_unknown_client():
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(None),
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1)),
        _clinic_repo(),
    )

    with pytest.raises(UserNotFoundError):
        await service.create_appointment(
            999,
            {"phone": "+998901234567", "appointment_datetime": "2026-07-10 14:30", "purpose": "Консультация"},
        )


@pytest.mark.asyncio
async def test_create_appointment_rejects_non_staff():
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(_client()),
        FakeStaffRepo(None),
        FakeClinicRepo(None),
    )

    with pytest.raises(RoleError):
        await service.create_appointment(
            999,
            {"phone": "+998901234567", "appointment_datetime": "2026-07-10 14:30", "purpose": "Консультация"},
        )


def _staff_member(staff_id=99, telegram_user_id=999, clinic_id=1, full_name="Петров Петр"):
    return User(
        full_name=full_name,
        phone="+998907654321",
        role=Role.ADMIN,
        telegram_user_id=telegram_user_id,
        ID=staff_id,
        clinic_id=clinic_id,
        clinic_name="Зуб Мудрости",
    )


def _booking_client(telegram_user_id=555, clinic_id=1):
    return User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=telegram_user_id,
        ID=7,
        clinic_id=clinic_id,
        clinic_name="Зуб Мудрости",
    )


@pytest.mark.asyncio
async def test_list_bookable_staff_returns_clinic_staff():
    client = _booking_client()
    staff = _staff_member()
    user_repo = FakeUserRepo(client=client, staff_by_clinic={1: [staff]})
    service = AppointmentManagement(FakeAppointmentRepository(), user_repo, FakeStaffRepo(None), _clinic_repo())

    staff_list = await service.list_bookable_staff(client.telegram_user_id)

    assert staff_list == [staff]


@pytest.mark.asyncio
async def test_list_bookable_staff_raises_when_client_not_found():
    user_repo = FakeUserRepo(client=None)
    service = AppointmentManagement(FakeAppointmentRepository(), user_repo, FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(UserNotFoundError):
        await service.list_bookable_staff(555)


@pytest.mark.asyncio
async def test_list_bookable_staff_excludes_clinic_scope_admins():
    """Reception/manager admins with visibility_scope='clinic' are not doctors and
    must not appear in the self-booking staff-selection keyboard."""
    client = _booking_client()
    own_scope_doctor = _staff_member(staff_id=99, telegram_user_id=999, full_name="Петров Петр")
    clinic_scope_admin = _staff_member(staff_id=100, telegram_user_id=1000, full_name="Артём Управляющий")
    clinic_scope_admin.visibility_scope = "clinic"
    user_repo = FakeUserRepo(client=client, staff_by_clinic={1: [own_scope_doctor, clinic_scope_admin]})
    service = AppointmentManagement(FakeAppointmentRepository(), user_repo, FakeStaffRepo(None), _clinic_repo())

    staff_list = await service.list_bookable_staff(client.telegram_user_id)

    assert staff_list == [own_scope_doctor]
    assert clinic_scope_admin not in staff_list


@pytest.mark.asyncio
async def test_list_bookable_staff_keeps_own_and_none_scope_admins():
    client = _booking_client()
    none_scope = _staff_member(staff_id=99, telegram_user_id=999, full_name="Петров Петр")
    own_scope = _staff_member(staff_id=101, telegram_user_id=1001, full_name="Елена Врач")
    own_scope.visibility_scope = "own"
    user_repo = FakeUserRepo(client=client, staff_by_clinic={1: [none_scope, own_scope]})
    service = AppointmentManagement(FakeAppointmentRepository(), user_repo, FakeStaffRepo(None), _clinic_repo())

    staff_list = await service.list_bookable_staff(client.telegram_user_id)

    assert staff_list == [none_scope, own_scope]


# --- resolve_admin_appointment_filter ---

def _admin_with_scope(scope: str | None, admin_id=42, telegram_user_id=999):
    return User(
        full_name="Петров Петр",
        phone="+998907654321",
        role=Role.ADMIN,
        telegram_user_id=telegram_user_id,
        ID=admin_id,
        clinic_id=1,
        clinic_name="Зуб Мудрости",
        visibility_scope=scope,
    )


@pytest.mark.asyncio
async def test_resolve_admin_appointment_filter_none_scope_returns_own_admin_id():
    admin = _admin_with_scope(None)
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=admin.telegram_user_id, clinic_id=1)),
        _clinic_repo(),
    )

    clinic_id, doctor_id = await service.resolve_admin_appointment_filter(admin.telegram_user_id)

    assert (clinic_id, doctor_id) == (1, 42)


@pytest.mark.asyncio
async def test_resolve_admin_appointment_filter_own_scope_returns_own_admin_id():
    admin = _admin_with_scope("own")
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=admin.telegram_user_id, clinic_id=1)),
        _clinic_repo(),
    )

    clinic_id, doctor_id = await service.resolve_admin_appointment_filter(admin.telegram_user_id)

    assert (clinic_id, doctor_id) == (1, 42)


@pytest.mark.asyncio
async def test_resolve_admin_appointment_filter_clinic_scope_returns_no_doctor_filter():
    admin = _admin_with_scope("clinic")
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=admin.telegram_user_id, clinic_id=1)),
        _clinic_repo(),
    )

    clinic_id, doctor_id = await service.resolve_admin_appointment_filter(admin.telegram_user_id)

    assert (clinic_id, doctor_id) == (1, None)


# --- get_appointment_for_admin ---

def _appointment_with_doctor(appointment_id=1, clinic_id=1, doctor_id=None):
    return Appointment(
        clinic_id=clinic_id,
        client_id=7,
        doctor_id=doctor_id,
        datetime="2026-07-10 14:30",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        id=appointment_id,
    )


@pytest.mark.asyncio
async def test_get_appointment_for_admin_own_scope_blocks_other_doctor_same_clinic():
    admin = _admin_with_scope("own")
    other_doctor_appointment = _appointment_with_doctor(clinic_id=1, doctor_id=777)
    service = AppointmentManagement(
        FakeAppointmentRepository([other_doctor_appointment]),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=admin.telegram_user_id, clinic_id=1)),
        _clinic_repo(),
    )

    result = await service.get_appointment_for_admin(
        other_doctor_appointment.id, admin.telegram_user_id
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_appointment_for_admin_own_scope_blocks_other_clinic():
    admin = _admin_with_scope("own")
    other_clinic_appointment = _appointment_with_doctor(clinic_id=2, doctor_id=admin.ID)
    service = AppointmentManagement(
        FakeAppointmentRepository([other_clinic_appointment]),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=admin.telegram_user_id, clinic_id=1)),
        _clinic_repo(),
    )

    result = await service.get_appointment_for_admin(
        other_clinic_appointment.id, admin.telegram_user_id
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_appointment_for_admin_own_scope_allows_own_appointment():
    admin = _admin_with_scope("own")
    own_appointment = _appointment_with_doctor(clinic_id=1, doctor_id=admin.ID)
    service = AppointmentManagement(
        FakeAppointmentRepository([own_appointment]),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=admin.telegram_user_id, clinic_id=1)),
        _clinic_repo(),
    )

    result = await service.get_appointment_for_admin(own_appointment.id, admin.telegram_user_id)

    assert result is own_appointment


@pytest.mark.asyncio
async def test_get_appointment_for_admin_clinic_scope_allows_any_doctor_same_clinic():
    admin = _admin_with_scope("clinic")
    other_doctor_appointment = _appointment_with_doctor(clinic_id=1, doctor_id=777)
    service = AppointmentManagement(
        FakeAppointmentRepository([other_doctor_appointment]),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=admin.telegram_user_id, clinic_id=1)),
        _clinic_repo(),
    )

    result = await service.get_appointment_for_admin(
        other_doctor_appointment.id, admin.telegram_user_id
    )

    assert result is other_doctor_appointment


@pytest.mark.asyncio
async def test_get_appointment_for_admin_clinic_scope_blocks_other_clinic():
    admin = _admin_with_scope("clinic")
    other_clinic_appointment = _appointment_with_doctor(clinic_id=2, doctor_id=777)
    service = AppointmentManagement(
        FakeAppointmentRepository([other_clinic_appointment]),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=admin.telegram_user_id, clinic_id=1)),
        _clinic_repo(),
    )

    result = await service.get_appointment_for_admin(
        other_clinic_appointment.id, admin.telegram_user_id
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_appointment_for_admin_returns_none_when_admin_user_missing():
    own_appointment = _appointment_with_doctor(clinic_id=1, doctor_id=42)
    service = AppointmentManagement(
        FakeAppointmentRepository([own_appointment]),
        FakeUserRepo(admin=None),
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1)),
        _clinic_repo(),
    )

    result = await service.get_appointment_for_admin(own_appointment.id, 999)

    assert result is None


@pytest.mark.asyncio
async def test_get_appointment_for_admin_returns_none_when_appointment_missing():
    admin = _admin_with_scope("clinic")
    service = AppointmentManagement(
        FakeAppointmentRepository([]),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=admin.telegram_user_id, clinic_id=1)),
        _clinic_repo(),
    )

    result = await service.get_appointment_for_admin(999, admin.telegram_user_id)

    assert result is None


@pytest.mark.asyncio
async def test_create_self_booking_creates_pending_client_appointment():
    client = _booking_client()
    staff = _staff_member()
    appt_repo = FakeAppointmentRepository()
    user_repo = FakeUserRepo(client=client, users_by_id={staff.ID: staff})
    service = AppointmentManagement(appt_repo, user_repo, FakeStaffRepo(None), _clinic_repo())

    appointment = await service.create_self_booking(
        client.telegram_user_id,
        {
            "staff_user_id": staff.ID,
            "appointment_datetime": _future_datetime(),
            "complaint": "Болит зуб",
        },
    )

    assert appt_repo.created == [appointment]
    assert appointment.clinic_id == client.clinic_id
    assert appointment.client_id == client.ID
    assert appointment.doctor_id == staff.ID
    assert appointment.created_by_telegram_id == staff.telegram_user_id
    assert appointment.created_by is CreatedBy.CLIENT
    assert appointment.status is AppointmentStatus.PENDING
    assert appointment.purpose == "Болит зуб"


@pytest.mark.asyncio
async def test_create_self_booking_raises_when_client_not_found():
    staff = _staff_member()
    user_repo = FakeUserRepo(client=None, users_by_id={staff.ID: staff})
    service = AppointmentManagement(FakeAppointmentRepository(), user_repo, FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(UserNotFoundError):
        await service.create_self_booking(
            555,
            {"staff_user_id": staff.ID, "appointment_datetime": "2026-07-10 14:30", "complaint": "Болит зуб"},
        )


@pytest.mark.asyncio
async def test_create_self_booking_raises_when_staff_not_found():
    client = _booking_client()
    user_repo = FakeUserRepo(client=client, users_by_id={})
    service = AppointmentManagement(FakeAppointmentRepository(), user_repo, FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(UserNotFoundError):
        await service.create_self_booking(
            client.telegram_user_id,
            {"staff_user_id": 12345, "appointment_datetime": "2026-07-10 14:30", "complaint": "Болит зуб"},
        )


@pytest.mark.asyncio
async def test_create_self_booking_succeeds_with_no_pending_requests():
    client = _booking_client()
    staff = _staff_member()
    appt_repo = FakeAppointmentRepository()
    user_repo = FakeUserRepo(client=client, users_by_id={staff.ID: staff})
    service = AppointmentManagement(appt_repo, user_repo, FakeStaffRepo(None), _clinic_repo())

    appointment = await service.create_self_booking(
        client.telegram_user_id,
        {"staff_user_id": staff.ID, "appointment_datetime": _future_datetime(), "complaint": "Болит зуб"},
    )

    assert appointment.status is AppointmentStatus.PENDING


def _self_booked_appointment(appointment_id=1, client_id=7, status=AppointmentStatus.PENDING, proposed_datetime=None):
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        datetime="2026-07-10 14:30",
        purpose="Болит зуб",
        created_by=CreatedBy.CLIENT,
        status=status,
        id=appointment_id,
        proposed_datetime=proposed_datetime,
    )


def _admin_pending_appointment(appointment_id=1, client_id=7):
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        datetime="2026-07-10 14:30",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        id=appointment_id,
    )


@pytest.mark.asyncio
async def test_ensure_pending_limit_raises_with_existing_pending_self_booking():
    client = _booking_client()
    appt_repo = FakeAppointmentRepository([_self_booked_appointment(client_id=client.ID)])
    service = AppointmentManagement(appt_repo, FakeUserRepo(client=client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(PendingRequestLimitExceededError):
        await service.ensure_pending_limit_not_exceeded(client.telegram_user_id)


@pytest.mark.asyncio
async def test_ensure_pending_limit_raises_when_proposal_outstanding():
    client = _booking_client()
    appt_repo = FakeAppointmentRepository(
        [_self_booked_appointment(client_id=client.ID, proposed_datetime="2026-07-11 10:00")]
    )
    service = AppointmentManagement(appt_repo, FakeUserRepo(client=client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(PendingRequestLimitExceededError):
        await service.ensure_pending_limit_not_exceeded(client.telegram_user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.EXPIRED,
    ],
)
async def test_ensure_pending_limit_allows_when_self_booking_is_finalized(status):
    client = _booking_client()
    appt_repo = FakeAppointmentRepository([_self_booked_appointment(client_id=client.ID, status=status)])
    service = AppointmentManagement(appt_repo, FakeUserRepo(client=client), FakeStaffRepo(None), _clinic_repo())

    await service.ensure_pending_limit_not_exceeded(client.telegram_user_id)


@pytest.mark.asyncio
async def test_ensure_pending_limit_ignores_admin_created_pending_appointment():
    client = _booking_client()
    appt_repo = FakeAppointmentRepository([_admin_pending_appointment(client_id=client.ID)])
    service = AppointmentManagement(appt_repo, FakeUserRepo(client=client), FakeStaffRepo(None), _clinic_repo())

    await service.ensure_pending_limit_not_exceeded(client.telegram_user_id)


@pytest.mark.asyncio
async def test_search_appointments_returns_client_appointments():
    service = AppointmentManagement(
        FakeAppointmentRepository([_appointment()]),
        FakeUserRepo(_client()),
        FakeStaffRepo(None),
        _clinic_repo(),
    )

    appointments = await service.search_appointments({"phone": "+998901234567"})

    assert len(appointments) == 1
    assert appointments[0].id == 1


@pytest.mark.asyncio
async def test_search_appointments_raises_when_empty():
    service = AppointmentManagement(
        FakeAppointmentRepository([]),
        FakeUserRepo(_client()),
        FakeStaffRepo(None),
        _clinic_repo(),
    )

    with pytest.raises(AppointmentNotFoundError):
        await service.search_appointments({"phone": "+998901234567"})


@pytest.mark.asyncio
async def test_update_status():
    appt_repo = FakeAppointmentRepository([_appointment()])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.update_status(1, AppointmentStatus.CONFIRMED)

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CONFIRMED)]


@pytest.mark.asyncio
async def test_update_datetime_validates_and_persists():
    appt_repo = FakeAppointmentRepository([_appointment()])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.update_datetime(1, "2026-08-01 09:00")

    assert appointment.datetime == "2026-08-01 09:00"
    assert appt_repo.updated[0][0] == 1


@pytest.mark.asyncio
async def test_update_price_validates_and_persists():
    appt_repo = FakeAppointmentRepository([_appointment()])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.update_price(1, 150000.0)

    assert appointment.price == 150000.0
    assert appt_repo.price_updates == [(1, 150000.0)]


@pytest.mark.asyncio
async def test_update_price_rejects_negative_price():
    from bot.exceptions.appointment_exceptions import InvalidPriceError

    appt_repo = FakeAppointmentRepository([_appointment()])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(InvalidPriceError):
        await service.update_price(1, -100.0)


@pytest.mark.asyncio
async def test_get_appointment_with_client_info_returns_appointment_and_client():
    appt_repo = FakeAppointmentRepository([_appointment()])
    client = _client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    appointment, retrieved_client = await service.get_appointment_with_client_info(1)

    assert appointment.id == 1
    assert retrieved_client.ID == client.ID
    assert retrieved_client.full_name == client.full_name


@pytest.mark.asyncio
async def test_get_appointment_with_client_info_returns_none_client_if_not_found():
    appt_repo = FakeAppointmentRepository([_appointment()])
    service = AppointmentManagement(appt_repo, FakeUserRepo(None), FakeStaffRepo(None), _clinic_repo())

    appointment, retrieved_client = await service.get_appointment_with_client_info(1)

    assert appointment.id == 1
    assert retrieved_client is None


@pytest.mark.asyncio
async def test_get_appointment_with_client_info_raises_if_appointment_not_found():
    appt_repo = FakeAppointmentRepository([])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentNotFoundError):
        await service.get_appointment_with_client_info(999)


def _appointment_at(
    appointment_id, dt, client_id=7, status=AppointmentStatus.PENDING, created_by=CreatedBy.CLIENT,
    proposed_datetime=None, proposed_by=None,
):
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        datetime=dt.strftime("%Y-%m-%d %H:%M:%S"),
        purpose="Консультация",
        created_by=created_by,
        status=status,
        id=appointment_id,
        proposed_datetime=proposed_datetime,
        proposed_by=proposed_by,
    )


def _owning_client(telegram_user_id=555):
    return User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=telegram_user_id,
        ID=7,
    )


@pytest.mark.asyncio
async def test_confirm_appointment_by_client_updates_status_for_owner():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), created_by=CreatedBy.ADMIN)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.confirm_appointment_by_client(1, client.telegram_user_id)

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CONFIRMED)]


@pytest.mark.asyncio
async def test_confirm_appointment_by_client_raises_not_found_for_wrong_owner():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository([_appointment_at(1, now + timedelta(days=1))])
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentNotFoundError):
        await service.confirm_appointment_by_client(1, telegram_user_id=999)


@pytest.mark.asyncio
async def test_confirm_appointment_by_client_succeeds_from_pending_when_admin_created():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.PENDING, created_by=CreatedBy.ADMIN)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.confirm_appointment_by_client(1, client.telegram_user_id)

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CONFIRMED)]


@pytest.mark.asyncio
async def test_confirm_appointment_by_client_raises_when_self_booked_and_pending():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.PENDING, created_by=CreatedBy.CLIENT)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AwaitingClinicDecisionError):
        await service.confirm_appointment_by_client(1, client.telegram_user_id)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_confirm_appointment_by_client_reconfirm_is_noop_success():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.CONFIRMED)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.confirm_appointment_by_client(1, client.telegram_user_id)

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CONFIRMED)]


@pytest.mark.asyncio
async def test_confirm_appointment_by_client_raises_when_cancelled():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.CANCELLED)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.confirm_appointment_by_client(1, client.telegram_user_id)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_confirm_appointment_by_client_raises_when_completed():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.COMPLETED)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.confirm_appointment_by_client(1, client.telegram_user_id)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_confirm_appointment_by_client_raises_when_no_show():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.NO_SHOW)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.confirm_appointment_by_client(1, client.telegram_user_id)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_cancel_appointment_by_client_blocked_within_1h_when_cutoff_enforced():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository([_appointment_at(1, now + timedelta(minutes=30))])
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(CancellationWindowExpiredError):
        await service.cancel_appointment_by_client(1, client.telegram_user_id, enforce_cutoff=True)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_cancel_appointment_by_client_blocked_for_past_appointment_when_cutoff_enforced():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository([_appointment_at(1, now - timedelta(hours=1))])
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(CancellationWindowExpiredError):
        await service.cancel_appointment_by_client(1, client.telegram_user_id, enforce_cutoff=True)


@pytest.mark.asyncio
async def test_cancel_appointment_by_client_allowed_outside_1h_window():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository([_appointment_at(1, now + timedelta(hours=3))])
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.cancel_appointment_by_client(1, client.telegram_user_id, enforce_cutoff=True)

    assert appointment.status is AppointmentStatus.CANCELLED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CANCELLED)]


@pytest.mark.asyncio
async def test_cancel_appointment_by_client_bypasses_cutoff_when_disabled():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository([_appointment_at(1, now + timedelta(minutes=30))])
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.cancel_appointment_by_client(1, client.telegram_user_id, enforce_cutoff=False)

    assert appointment.status is AppointmentStatus.CANCELLED


@pytest.mark.asyncio
async def test_cancel_appointment_by_client_raises_not_found_for_wrong_owner():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository([_appointment_at(1, now + timedelta(days=1))])
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentNotFoundError):
        await service.cancel_appointment_by_client(1, telegram_user_id=999, enforce_cutoff=True)


@pytest.mark.asyncio
async def test_cancel_appointment_by_client_raises_when_cancelled():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.CANCELLED)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.cancel_appointment_by_client(1, client.telegram_user_id, enforce_cutoff=False)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_cancel_appointment_by_client_raises_when_completed():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.COMPLETED)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.cancel_appointment_by_client(1, client.telegram_user_id, enforce_cutoff=False)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_cancel_appointment_by_client_raises_when_no_show():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.NO_SHOW)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.cancel_appointment_by_client(1, client.telegram_user_id, enforce_cutoff=False)

    assert appt_repo.status_updates == []


# --- Booking negotiation (confirm/reject/propose/accept/reject-proposal) ---


def _pending_client_request(
    appointment_id=1, client_id=7, proposed_datetime=None, status=AppointmentStatus.PENDING, proposed_by=None
):
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        datetime="2026-07-10 14:30",
        purpose="Болит зуб",
        created_by=CreatedBy.CLIENT,
        status=status,
        id=appointment_id,
        proposed_datetime=proposed_datetime,
        proposed_by=proposed_by,
    )


@pytest.mark.asyncio
async def test_confirm_pending_request_updates_status():
    appt_repo = FakeAppointmentRepository([_pending_client_request()])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.confirm_pending_request(1, staff_telegram_id=999)

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CONFIRMED)]


@pytest.mark.asyncio
async def test_confirm_pending_request_blocked_when_proposal_pending():
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(proposed_datetime="2026-07-11 10:00")]
    )
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(NegotiationInProgressError):
        await service.confirm_pending_request(1, staff_telegram_id=999)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_confirm_pending_request_raises_when_finalized():
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(status=AppointmentStatus.EXPIRED)]
    )
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.confirm_pending_request(1, staff_telegram_id=999)


@pytest.mark.asyncio
async def test_reject_pending_request_updates_status():
    appt_repo = FakeAppointmentRepository([_pending_client_request()])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.reject_pending_request(1, staff_telegram_id=999)

    assert appointment.status is AppointmentStatus.CANCELLED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CANCELLED)]


@pytest.mark.asyncio
async def test_reject_pending_request_blocked_when_proposal_pending():
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(proposed_datetime="2026-07-11 10:00")]
    )
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(NegotiationInProgressError):
        await service.reject_pending_request(1, staff_telegram_id=999)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_propose_new_datetime_sets_proposed_without_touching_status_or_datetime():
    appt_repo = FakeAppointmentRepository([_pending_client_request()])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())
    proposed_datetime = _future_datetime(days=3, time_str="10:00")

    appointment = await service.propose_new_datetime(1, staff_telegram_id=999, proposed_datetime=proposed_datetime)

    assert appointment.proposed_datetime == proposed_datetime
    assert appointment.proposed_by is CreatedBy.ADMIN
    assert appointment.status is AppointmentStatus.PENDING
    assert appointment.datetime == "2026-07-10 14:30"
    assert appt_repo.proposed_datetime_updates == [(1, proposed_datetime)]
    assert appt_repo.proposed_by_updates == [(1, CreatedBy.ADMIN)]
    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_propose_new_datetime_raises_when_own_proposal_already_outstanding():
    """Admin cannot propose a second time while still waiting on the client's
    answer to its own earlier proposal (proposed_by=ADMIN)."""
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(proposed_datetime="2026-07-11 10:00", proposed_by=CreatedBy.ADMIN)]
    )
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(NegotiationInProgressError):
        await service.propose_new_datetime(1, staff_telegram_id=999, proposed_datetime="2026-07-12 10:00")

    assert appt_repo.proposed_datetime_updates == []
    assert appt_repo.proposed_by_updates == []


@pytest.mark.asyncio
async def test_propose_new_datetime_overwrites_when_proposed_by_client():
    """New allowed behavior: an admin counter-proposing over a CLIENT proposal
    (client asked for a reschedule, admin now offers a different time) is not
    blocked by the guard -- it overwrites proposed_datetime/proposed_by."""
    now = get_current_tashkent_datetime()
    new_proposed_datetime = _future_datetime(days=4, time_str="10:00")
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(
            1, now + timedelta(days=1), status=AppointmentStatus.CONFIRMED,
            proposed_datetime="2026-07-11 10:00", proposed_by=CreatedBy.CLIENT,
        )]
    )
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.propose_new_datetime(1, staff_telegram_id=999, proposed_datetime=new_proposed_datetime)

    assert appointment.proposed_datetime == new_proposed_datetime
    assert appointment.proposed_by is CreatedBy.ADMIN
    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.proposed_datetime_updates == [(1, new_proposed_datetime)]
    assert appt_repo.proposed_by_updates == [(1, CreatedBy.ADMIN)]


@pytest.mark.asyncio
async def test_propose_new_datetime_succeeds_on_confirmed_appointment_with_no_outstanding_proposal():
    """propose_new_datetime is no longer restricted to PENDING self-booking
    requests -- it now also works on a CONFIRMED appointment with a clean
    negotiation state (this is the admin-initiated reschedule proposal flow)."""
    now = get_current_tashkent_datetime()
    proposed_datetime = _future_datetime(days=3, time_str="10:00")
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.CONFIRMED)]
    )
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.propose_new_datetime(1, staff_telegram_id=999, proposed_datetime=proposed_datetime)

    assert appointment.proposed_datetime == proposed_datetime
    assert appointment.proposed_by is CreatedBy.ADMIN
    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.proposed_datetime_updates == [(1, proposed_datetime)]
    assert appt_repo.proposed_by_updates == [(1, CreatedBy.ADMIN)]


@pytest.mark.asyncio
async def test_propose_new_datetime_raises_when_finalized():
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(status=AppointmentStatus.CANCELLED)]
    )
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.propose_new_datetime(1, staff_telegram_id=999, proposed_datetime="2026-07-11 10:00")


@pytest.mark.asyncio
async def test_accept_proposed_datetime_promotes_proposal_and_confirms():
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(proposed_datetime="2026-07-11 10:00", proposed_by=CreatedBy.ADMIN)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.accept_proposed_datetime(1, client.telegram_user_id)

    assert appointment.datetime == "2026-07-11 10:00"
    assert appointment.proposed_datetime is None
    assert appointment.proposed_by is None
    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.updated[0][0] == 1
    assert appt_repo.proposed_datetime_updates == [(1, None)]
    assert appt_repo.proposed_by_updates == [(1, None)]


@pytest.mark.asyncio
async def test_accept_proposed_datetime_raises_when_no_proposal():
    appt_repo = FakeAppointmentRepository([_pending_client_request()])
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(NoPendingProposalError):
        await service.accept_proposed_datetime(1, client.telegram_user_id)


@pytest.mark.asyncio
async def test_accept_proposed_datetime_raises_not_found_for_wrong_owner():
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(proposed_datetime="2026-07-11 10:00")]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentNotFoundError):
        await service.accept_proposed_datetime(1, telegram_user_id=999)


@pytest.mark.asyncio
async def test_reject_proposed_datetime_cancels_and_clears_proposal():
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(proposed_datetime="2026-07-11 10:00", proposed_by=CreatedBy.ADMIN)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.reject_proposed_datetime(1, client.telegram_user_id)

    assert appointment.status is AppointmentStatus.CANCELLED
    assert appt_repo.proposed_datetime_updates == [(1, None)]
    assert appt_repo.proposed_by_updates == [(1, None)]
    assert appt_repo.status_updates == [(1, AppointmentStatus.CANCELLED)]


@pytest.mark.asyncio
async def test_reject_proposed_datetime_raises_when_no_proposal():
    appt_repo = FakeAppointmentRepository([_pending_client_request()])
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(NoPendingProposalError):
        await service.reject_proposed_datetime(1, client.telegram_user_id)


@pytest.mark.asyncio
async def test_accept_proposed_datetime_raises_when_proposed_by_client():
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(proposed_datetime="2026-07-11 10:00", proposed_by=CreatedBy.CLIENT)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(NoPendingProposalError):
        await service.accept_proposed_datetime(1, client.telegram_user_id)

    assert appt_repo.updated == []
    assert appt_repo.proposed_datetime_updates == []


@pytest.mark.asyncio
async def test_reject_proposed_datetime_raises_when_proposed_by_client():
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(proposed_datetime="2026-07-11 10:00", proposed_by=CreatedBy.CLIENT)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(NoPendingProposalError):
        await service.reject_proposed_datetime(1, client.telegram_user_id)

    assert appt_repo.proposed_datetime_updates == []
    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_accept_proposed_datetime_raises_when_expired_with_stale_proposal():
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(proposed_datetime="2026-07-11 10:00", status=AppointmentStatus.EXPIRED)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.accept_proposed_datetime(1, client.telegram_user_id)

    assert appt_repo.status_updates == []
    assert appt_repo.updated == []
    assert appt_repo.proposed_datetime_updates == []


@pytest.mark.asyncio
async def test_reject_proposed_datetime_raises_when_expired_with_stale_proposal():
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(proposed_datetime="2026-07-11 10:00", status=AppointmentStatus.EXPIRED)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.reject_proposed_datetime(1, client.telegram_user_id)

    assert appt_repo.status_updates == []
    assert appt_repo.proposed_datetime_updates == []


@pytest.mark.asyncio
async def test_confirm_appointment_by_client_raises_when_expired():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.EXPIRED)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.confirm_appointment_by_client(1, client.telegram_user_id)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_cancel_appointment_by_client_raises_when_expired():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.EXPIRED)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.cancel_appointment_by_client(1, client.telegram_user_id, enforce_cutoff=False)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_cancel_appointment_by_client_clears_outstanding_proposal():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(
            1, now + timedelta(days=1), status=AppointmentStatus.CONFIRMED,
            proposed_datetime="2026-07-11 10:00", proposed_by=CreatedBy.CLIENT,
        )]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.cancel_appointment_by_client(1, client.telegram_user_id, enforce_cutoff=False)

    assert appointment.status is AppointmentStatus.CANCELLED
    assert appt_repo.proposed_datetime_updates == [(1, None)]
    assert appt_repo.proposed_by_updates == [(1, None)]


# --- Client-initiated reschedule (Phase 3a) ---


@pytest.mark.asyncio
async def test_request_reschedule_by_client_succeeds_when_confirmed():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.CONFIRMED)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    new_dt = (now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    appointment = await service.request_reschedule_by_client(1, client.telegram_user_id, new_dt)

    assert appointment.proposed_datetime == new_dt
    assert appointment.proposed_by is CreatedBy.CLIENT
    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.proposed_datetime_updates == [(1, new_dt)]
    assert appt_repo.proposed_by_updates == [(1, CreatedBy.CLIENT)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        AppointmentStatus.CANCELLED,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.EXPIRED,
    ],
)
async def test_request_reschedule_by_client_raises_when_finalized(status):
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository([_appointment_at(1, now + timedelta(days=1), status=status)])
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    new_dt = (now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.request_reschedule_by_client(1, client.telegram_user_id, new_dt)


@pytest.mark.asyncio
async def test_request_reschedule_by_client_succeeds_when_pending_edits_datetime_directly():
    """Own PENDING self-booking request: client edits datetime directly on the same
    row, no proposal negotiation (the clinic hasn't confirmed anything yet)."""
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.PENDING)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    new_dt = (now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    appointment = await service.request_reschedule_by_client(1, client.telegram_user_id, new_dt)

    assert appointment.datetime == new_dt
    assert appointment.status is AppointmentStatus.PENDING
    assert appointment.proposed_datetime is None
    assert appt_repo.updated == [(1, appointment)]
    assert appt_repo.proposed_datetime_updates == []
    assert appt_repo.proposed_by_updates == []


@pytest.mark.asyncio
async def test_request_reschedule_by_client_succeeds_when_pending_and_admin_created():
    """PR3: an admin-created PENDING request (an invite the client hasn't answered
    yet) is NOT the client's own self-booking row, so it does not go through the
    direct-edit branch -- but it is no longer categorically blocked either. It now
    goes through the same negotiation branch as a CONFIRMED appointment: the client's
    counter-time is recorded as a proposal (proposed_by=CLIENT) awaiting the clinic's
    decision, the appointment's own status/datetime stay untouched."""
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.PENDING, created_by=CreatedBy.ADMIN)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    original_dt = appt_repo.appointments[0].datetime
    new_dt = (now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    appointment = await service.request_reschedule_by_client(1, client.telegram_user_id, new_dt)

    assert appointment.status is AppointmentStatus.PENDING
    assert appointment.datetime == original_dt
    assert appointment.proposed_datetime == new_dt
    assert appointment.proposed_by is CreatedBy.CLIENT
    assert appt_repo.updated == []
    assert appt_repo.proposed_datetime_updates == [(1, new_dt)]
    assert appt_repo.proposed_by_updates == [(1, CreatedBy.CLIENT)]


@pytest.mark.asyncio
async def test_request_reschedule_by_client_raises_when_pending_admin_created_proposal_already_outstanding():
    """PENDING+ADMIN with a proposal already outstanding (either side) is still
    blocked by NegotiationInProgressError -- the new PR3 branch only opens the door
    to a first proposal, it does not allow stacking a second one."""
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(
            1, now + timedelta(days=1), status=AppointmentStatus.PENDING, created_by=CreatedBy.ADMIN,
            proposed_datetime="2026-07-11 10:00", proposed_by=CreatedBy.ADMIN,
        )]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    new_dt = (now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    with pytest.raises(NegotiationInProgressError):
        await service.request_reschedule_by_client(1, client.telegram_user_id, new_dt)

    assert appt_repo.updated == []
    assert appt_repo.proposed_datetime_updates == []
    assert appt_repo.proposed_by_updates == []


@pytest.mark.asyncio
async def test_request_reschedule_by_client_raises_when_pending_new_time_within_lead_time():
    """The 2h30 minimum lead-time guard must still apply to the PENDING direct-edit
    branch: it fires before the datetime is ever written to the row."""
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=3), status=AppointmentStatus.PENDING)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    new_dt = (now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
    with pytest.raises(BookingTooSoonError):
        await service.request_reschedule_by_client(1, client.telegram_user_id, new_dt)

    assert appt_repo.updated == []
    assert appt_repo.proposed_datetime_updates == []
    assert appt_repo.proposed_by_updates == []


@pytest.mark.asyncio
async def test_request_reschedule_by_client_succeeds_when_old_time_is_imminent_but_new_time_is_not():
    """The cutoff must be checked against the NEW datetime, not the old one: a client
    rescheduling away from an imminent appointment to a far-future slot must succeed."""
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(minutes=5), status=AppointmentStatus.CONFIRMED)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    new_dt = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    appointment = await service.request_reschedule_by_client(1, client.telegram_user_id, new_dt)

    assert appointment.proposed_datetime == new_dt
    assert appointment.proposed_by is CreatedBy.CLIENT
    assert appt_repo.proposed_datetime_updates == [(1, new_dt)]


@pytest.mark.asyncio
async def test_request_reschedule_by_client_raises_when_new_time_within_lead_time():
    """The 2h30 minimum lead-time guard must reject a reschedule when the NEW proposed
    datetime is too soon, regardless of how far away the original appointment is."""
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=3), status=AppointmentStatus.CONFIRMED)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    new_dt = (now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")
    with pytest.raises(BookingTooSoonError):
        await service.request_reschedule_by_client(1, client.telegram_user_id, new_dt)

    assert appt_repo.proposed_datetime_updates == []


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_proposed_by", [CreatedBy.ADMIN, CreatedBy.CLIENT])
@pytest.mark.parametrize("status", [AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING])
async def test_request_reschedule_by_client_raises_when_proposal_already_outstanding(status, existing_proposed_by):
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(
            1, now + timedelta(days=1), status=status,
            proposed_datetime="2026-07-11 10:00", proposed_by=existing_proposed_by,
        )]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    new_dt = (now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    with pytest.raises(NegotiationInProgressError):
        await service.request_reschedule_by_client(1, client.telegram_user_id, new_dt)

    assert appt_repo.updated == []
    assert appt_repo.proposed_datetime_updates == []
    assert appt_repo.proposed_by_updates == []


@pytest.mark.asyncio
async def test_accept_client_reschedule_promotes_datetime_and_clears_proposal():
    now = get_current_tashkent_datetime()
    new_dt = (now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(
            1, now + timedelta(days=1), status=AppointmentStatus.CONFIRMED,
            proposed_datetime=new_dt, proposed_by=CreatedBy.CLIENT,
        )]
    )
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client()), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.accept_client_reschedule(1, staff_telegram_id=999)

    assert appointment.datetime == new_dt
    assert appointment.proposed_datetime is None
    assert appointment.proposed_by is None
    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.updated[0][0] == 1
    assert appt_repo.proposed_datetime_updates == [(1, None)]
    assert appt_repo.proposed_by_updates == [(1, None)]


@pytest.mark.asyncio
async def test_accept_client_reschedule_confirms_pending_admin_created_appointment():
    """PR3: accepting a client's counter-proposal on a PENDING+ADMIN invite (the
    negotiation branch opened by request_reschedule_by_client) promotes the
    appointment straight to CONFIRMED at the proposed time -- this is the fix for
    the bug where accept_client_reschedule never touched status at all."""
    now = get_current_tashkent_datetime()
    new_dt = (now + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(
            1, now + timedelta(days=1), status=AppointmentStatus.PENDING, created_by=CreatedBy.ADMIN,
            proposed_datetime=new_dt, proposed_by=CreatedBy.CLIENT,
        )]
    )
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client()), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.accept_client_reschedule(1, staff_telegram_id=999)

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appointment.datetime == new_dt
    assert appointment.proposed_datetime is None
    assert appointment.proposed_by is None
    assert appt_repo.updated[0][0] == 1
    assert appt_repo.proposed_datetime_updates == [(1, None)]
    assert appt_repo.proposed_by_updates == [(1, None)]


@pytest.mark.asyncio
async def test_accept_client_reschedule_raises_when_proposed_by_admin():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(
            1, now + timedelta(days=1), status=AppointmentStatus.CONFIRMED,
            proposed_datetime="2026-07-11 10:00", proposed_by=CreatedBy.ADMIN,
        )]
    )
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(NoPendingProposalError):
        await service.accept_client_reschedule(1, staff_telegram_id=999)


@pytest.mark.asyncio
async def test_accept_client_reschedule_raises_when_no_proposal():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.CONFIRMED)]
    )
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(NoPendingProposalError):
        await service.accept_client_reschedule(1, staff_telegram_id=999)


@pytest.mark.asyncio
async def test_reject_client_reschedule_cancels_appointment_and_clears_proposal():
    """Reject is now terminal: unlike the old behavior (appointment stays
    CONFIRMED at its original datetime), the whole appointment is cancelled,
    same as rejecting a pending request. The outstanding proposal fields are
    still cleared on the way there."""
    now = get_current_tashkent_datetime()
    original_dt = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(
            1, now + timedelta(days=1), status=AppointmentStatus.CONFIRMED,
            proposed_datetime="2026-07-11 10:00", proposed_by=CreatedBy.CLIENT,
        )]
    )
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client()), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.reject_client_reschedule(1, staff_telegram_id=999)

    assert appointment.status is AppointmentStatus.CANCELLED
    assert appointment.datetime == original_dt
    assert appt_repo.status_updates == [(1, AppointmentStatus.CANCELLED)]
    assert appt_repo.updated == []
    assert appt_repo.proposed_datetime_updates == [(1, None)]
    assert appt_repo.proposed_by_updates == [(1, None)]


@pytest.mark.asyncio
async def test_reject_client_reschedule_raises_when_proposed_by_admin():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(
            1, now + timedelta(days=1), status=AppointmentStatus.CONFIRMED,
            proposed_datetime="2026-07-11 10:00", proposed_by=CreatedBy.ADMIN,
        )]
    )
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(NoPendingProposalError):
        await service.reject_client_reschedule(1, staff_telegram_id=999)


# --- Slot conflict detection ---


def _appt(appointment_id, doctor_id, dt, status, created_by=CreatedBy.ADMIN,
          client_id=7, proposed_datetime=None, proposed_by=None):
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        doctor_id=doctor_id,
        datetime=dt,
        purpose="Консультация",
        created_by=created_by,
        status=status,
        id=appointment_id,
        proposed_datetime=proposed_datetime,
        proposed_by=proposed_by,
    )


@pytest.mark.asyncio
async def test_get_available_slots_excludes_confirmed_but_not_pending():
    doctor_id = 50
    day = date(2026, 7, 20)
    now = datetime(2026, 7, 1, 9, 0)

    appt_repo = FakeAppointmentRepository([
        _appt(1, doctor_id, "2026-07-20 10:30", AppointmentStatus.CONFIRMED),
        _appt(2, doctor_id, "2026-07-20 11:00", AppointmentStatus.PENDING),
    ])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    slots = await service.get_available_slots(doctor_id, day, now)

    assert "10:30" not in slots
    assert "11:00" in slots


@pytest.mark.asyncio
async def test_create_appointment_raises_when_slot_already_confirmed():
    admin = _staff_member()
    client = _booking_client()
    existing = _appt(1, admin.ID, "2026-07-10 14:30", AppointmentStatus.CONFIRMED, client_id=99)
    appt_repo = FakeAppointmentRepository([existing])
    user_repo = FakeUserRepo(client=client, admin=admin)
    service = AppointmentManagement(
        appt_repo, user_repo, FakeStaffRepo(Staff(telegram_user_id=admin.telegram_user_id, clinic_id=1)),
        _clinic_repo(),
    )

    with pytest.raises(SlotUnavailableError):
        await service.create_appointment(
            admin.telegram_user_id,
            {"phone": client.phone, "appointment_datetime": "2026-07-10 14:30", "purpose": "Консультация"},
        )

    assert appt_repo.created == []


@pytest.mark.asyncio
async def test_create_self_booking_raises_when_slot_already_confirmed():
    client = _booking_client()
    staff = _staff_member()
    appointment_datetime = _future_datetime()
    existing = _appt(1, staff.ID, appointment_datetime, AppointmentStatus.CONFIRMED, client_id=99)
    appt_repo = FakeAppointmentRepository([existing])
    user_repo = FakeUserRepo(client=client, users_by_id={staff.ID: staff})
    service = AppointmentManagement(appt_repo, user_repo, FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(SlotUnavailableError):
        await service.create_self_booking(
            client.telegram_user_id,
            {"staff_user_id": staff.ID, "appointment_datetime": appointment_datetime, "complaint": "Болит зуб"},
        )

    assert appt_repo.created == []


@pytest.mark.asyncio
async def test_confirm_appointment_by_client_raises_when_slot_taken_by_another_confirmed():
    own = _appt(1, 50, "2026-07-10 14:30", AppointmentStatus.PENDING, created_by=CreatedBy.ADMIN, client_id=7)
    other = _appt(2, 50, "2026-07-10 14:30", AppointmentStatus.CONFIRMED, client_id=8)
    appt_repo = FakeAppointmentRepository([own, other])
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(SlotUnavailableError):
        await service.confirm_appointment_by_client(1, client.telegram_user_id)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_confirm_appointment_by_client_reconfirm_does_not_self_conflict():
    """Re-confirming an appointment that is already CONFIRMED must not treat its
    own row as a conflicting slot (self-exclusion by appointment id)."""
    own = _appt(1, 50, "2026-07-10 14:30", AppointmentStatus.CONFIRMED, created_by=CreatedBy.ADMIN, client_id=7)
    appt_repo = FakeAppointmentRepository([own])
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.confirm_appointment_by_client(1, client.telegram_user_id)

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CONFIRMED)]


@pytest.mark.asyncio
async def test_confirm_pending_request_raises_when_slot_taken_by_another_confirmed():
    own = _appt(1, 50, "2026-07-10 14:30", AppointmentStatus.PENDING, created_by=CreatedBy.CLIENT, client_id=7)
    other = _appt(2, 50, "2026-07-10 14:30", AppointmentStatus.CONFIRMED, client_id=8)
    appt_repo = FakeAppointmentRepository([own, other])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(SlotUnavailableError):
        await service.confirm_pending_request(1, staff_telegram_id=999)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_confirm_pending_request_succeeds_when_slot_free():
    own = _appt(1, 50, "2026-07-10 14:30", AppointmentStatus.PENDING, created_by=CreatedBy.CLIENT, client_id=7)
    appt_repo = FakeAppointmentRepository([own])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.confirm_pending_request(1, staff_telegram_id=999)

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CONFIRMED)]


@pytest.mark.asyncio
async def test_propose_new_datetime_raises_when_proposed_slot_already_confirmed():
    proposed_datetime = _future_datetime(days=3, time_str="10:00")
    own = _appt(1, 50, "2026-07-10 14:30", AppointmentStatus.PENDING, created_by=CreatedBy.CLIENT, client_id=7)
    other = _appt(2, 50, proposed_datetime, AppointmentStatus.CONFIRMED, client_id=8)
    appt_repo = FakeAppointmentRepository([own, other])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(SlotUnavailableError):
        await service.propose_new_datetime(1, staff_telegram_id=999, proposed_datetime=proposed_datetime)

    assert appt_repo.proposed_datetime_updates == []
    assert appt_repo.proposed_by_updates == []


@pytest.mark.asyncio
async def test_accept_proposed_datetime_raises_when_proposed_slot_already_confirmed():
    own = _appt(
        1, 50, "2026-07-10 14:30", AppointmentStatus.PENDING, created_by=CreatedBy.CLIENT, client_id=7,
        proposed_datetime="2026-07-11 10:00", proposed_by=CreatedBy.ADMIN,
    )
    other = _appt(2, 50, "2026-07-11 10:00", AppointmentStatus.CONFIRMED, client_id=8)
    appt_repo = FakeAppointmentRepository([own, other])
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(SlotUnavailableError):
        await service.accept_proposed_datetime(1, client.telegram_user_id)

    assert appt_repo.updated == []
    assert appt_repo.proposed_datetime_updates == []


@pytest.mark.asyncio
async def test_accept_proposed_datetime_succeeds_when_only_own_confirmed_row_shares_the_day():
    """The appointment's own current CONFIRMED row (a different time, same day)
    must not be mistaken for a conflicting slot."""
    own = _appt(
        1, 50, "2026-07-10 14:30", AppointmentStatus.CONFIRMED, created_by=CreatedBy.CLIENT, client_id=7,
        proposed_datetime="2026-07-10 16:00", proposed_by=CreatedBy.ADMIN,
    )
    appt_repo = FakeAppointmentRepository([own])
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.accept_proposed_datetime(1, client.telegram_user_id)

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appointment.datetime == "2026-07-10 16:00"
    assert appt_repo.updated[0][0] == 1


@pytest.mark.asyncio
async def test_accept_client_reschedule_raises_when_proposed_slot_already_confirmed():
    own = _appt(
        1, 50, "2026-07-10 14:30", AppointmentStatus.CONFIRMED, created_by=CreatedBy.CLIENT, client_id=7,
        proposed_datetime="2026-07-11 10:00", proposed_by=CreatedBy.CLIENT,
    )
    other = _appt(2, 50, "2026-07-11 10:00", AppointmentStatus.CONFIRMED, client_id=8)
    appt_repo = FakeAppointmentRepository([own, other])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(SlotUnavailableError):
        await service.accept_client_reschedule(1, staff_telegram_id=999)

    assert appt_repo.updated == []
    assert appt_repo.proposed_datetime_updates == []


@pytest.mark.asyncio
async def test_accept_client_reschedule_succeeds_when_only_own_confirmed_row_shares_the_day():
    own = _appt(
        1, 50, "2026-07-10 14:30", AppointmentStatus.CONFIRMED, created_by=CreatedBy.CLIENT, client_id=7,
        proposed_datetime="2026-07-10 16:00", proposed_by=CreatedBy.CLIENT,
    )
    appt_repo = FakeAppointmentRepository([own])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client()), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.accept_client_reschedule(1, staff_telegram_id=999)

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appointment.datetime == "2026-07-10 16:00"
    assert appt_repo.updated[0][0] == 1


@pytest.mark.asyncio
async def test_two_pending_requests_for_same_doctor_and_slot_both_succeed():
    """PENDING never blocks a slot -- only a CONFIRMED appointment does. Two
    independent requests racing for the same doctor+datetime must both succeed
    while pending, leaving the clinic to resolve the collision manually."""
    admin = _staff_member()
    client = _booking_client()
    appt_repo = FakeAppointmentRepository()
    user_repo = FakeUserRepo(client=client, admin=admin)
    service = AppointmentManagement(
        appt_repo, user_repo, FakeStaffRepo(Staff(telegram_user_id=admin.telegram_user_id, clinic_id=1)),
        _clinic_repo(),
    )
    data = {"phone": client.phone, "appointment_datetime": _future_datetime(), "purpose": "Консультация"}

    first = await service.create_appointment(admin.telegram_user_id, data)
    appt_repo.appointments.append(first)
    second = await service.create_appointment(admin.telegram_user_id, data)

    assert first.status is AppointmentStatus.PENDING
    assert second.status is AppointmentStatus.PENDING
    assert len(appt_repo.created) == 2


# --- Zombie PENDING fix (item 1/4): MIN_LEAD_TIME boundary tests ---
#
# MIN_LEAD_TIME = 2h30 is the real internal threshold; every user-facing text
# says "2 hours" (the 30-minute buffer is intentionally hidden). These tests
# pin the exact 2h29/2h30 boundary by freezing `now` via patching
# get_current_tashkent_datetime, so the assertions never depend on wall-clock
# timing at whatever moment the suite happens to run.


@pytest.mark.asyncio
async def test_create_self_booking_raises_when_lead_time_is_exactly_2h29():
    """2h29 is 1 minute short of the hidden 2h30 buffer -- must still be
    rejected, proving the real threshold is not simply '2 hours'."""
    client = _booking_client()
    staff = _staff_member()
    appt_repo = FakeAppointmentRepository()
    user_repo = FakeUserRepo(client=client, users_by_id={staff.ID: staff})
    service = AppointmentManagement(appt_repo, user_repo, FakeStaffRepo(None), _clinic_repo())

    base = get_current_tashkent_datetime().replace(second=0, microsecond=0)
    with patch(
        "bot.services.appointment.appointment_management.get_current_tashkent_datetime",
        return_value=base,
    ):
        target = (base + timedelta(hours=2, minutes=29)).strftime("%Y-%m-%d %H:%M")

        with pytest.raises(BookingTooSoonError):
            await service.create_self_booking(
                client.telegram_user_id,
                {"staff_user_id": staff.ID, "appointment_datetime": target, "complaint": "Болит зуб"},
            )

    assert appt_repo.created == []


@pytest.mark.asyncio
async def test_create_self_booking_succeeds_when_lead_time_is_exactly_2h30():
    """2h30 is exactly the threshold; the guard is strict '<', so exactly
    2h30 must pass, not raise."""
    client = _booking_client()
    staff = _staff_member()
    appt_repo = FakeAppointmentRepository()
    user_repo = FakeUserRepo(client=client, users_by_id={staff.ID: staff})
    service = AppointmentManagement(appt_repo, user_repo, FakeStaffRepo(None), _clinic_repo())

    base = get_current_tashkent_datetime().replace(second=0, microsecond=0)
    with patch(
        "bot.services.appointment.appointment_management.get_current_tashkent_datetime",
        return_value=base,
    ):
        target = (base + timedelta(hours=2, minutes=30)).strftime("%Y-%m-%d %H:%M")

        appointment = await service.create_self_booking(
            client.telegram_user_id,
            {"staff_user_id": staff.ID, "appointment_datetime": target, "complaint": "Болит зуб"},
        )

    assert appointment.status is AppointmentStatus.PENDING
    assert appt_repo.created == [appointment]


@pytest.mark.asyncio
@pytest.mark.parametrize("minutes", [31, 45, 59])
async def test_create_self_booking_succeeds_when_lead_time_between_2h31_and_2h59(minutes):
    """Comfortably above the hidden buffer -- must pass for any value in this
    range. (That the reminder's own '-3h' arithmetic may itself be past-due
    for these same values is a separate, expected concern covered by a
    scheduler-level regression test, not a booking-validation failure.)"""
    client = _booking_client()
    staff = _staff_member()
    appt_repo = FakeAppointmentRepository()
    user_repo = FakeUserRepo(client=client, users_by_id={staff.ID: staff})
    service = AppointmentManagement(appt_repo, user_repo, FakeStaffRepo(None), _clinic_repo())

    now = get_current_tashkent_datetime()
    target = (now + timedelta(hours=2, minutes=minutes)).strftime("%Y-%m-%d %H:%M")

    appointment = await service.create_self_booking(
        client.telegram_user_id,
        {"staff_user_id": staff.ID, "appointment_datetime": target, "complaint": "Болит зуб"},
    )

    assert appointment.status is AppointmentStatus.PENDING


@pytest.mark.asyncio
async def test_request_reschedule_by_client_raises_when_lead_time_is_exactly_2h29():
    """request_reschedule_by_client replaced its old 1h cutoff check with the
    shared MIN_LEAD_TIME validation (see docs/zombie_pending_fix_prompt.md) --
    pin the exact 2h29 boundary here too, not just a loose 30-minute margin."""
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=3), status=AppointmentStatus.CONFIRMED)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    base = get_current_tashkent_datetime().replace(second=0, microsecond=0)
    with patch(
        "bot.services.appointment.appointment_management.get_current_tashkent_datetime",
        return_value=base,
    ):
        new_dt = (base + timedelta(hours=2, minutes=29)).strftime("%Y-%m-%d %H:%M")

        with pytest.raises(BookingTooSoonError):
            await service.request_reschedule_by_client(1, client.telegram_user_id, new_dt)

    assert appt_repo.proposed_datetime_updates == []


@pytest.mark.asyncio
async def test_request_reschedule_by_client_succeeds_when_lead_time_is_exactly_2h30():
    """Symmetric pass-side boundary check for request_reschedule_by_client:
    exactly 2h30 must not raise."""
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=3), status=AppointmentStatus.CONFIRMED)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    base = get_current_tashkent_datetime().replace(second=0, microsecond=0)
    with patch(
        "bot.services.appointment.appointment_management.get_current_tashkent_datetime",
        return_value=base,
    ):
        new_dt = (base + timedelta(hours=2, minutes=30)).strftime("%Y-%m-%d %H:%M")

        appointment = await service.request_reschedule_by_client(1, client.telegram_user_id, new_dt)

    assert appointment.proposed_datetime == new_dt
    assert appointment.proposed_by is CreatedBy.CLIENT
    assert appt_repo.proposed_datetime_updates == [(1, new_dt)]


# --- Zombie PENDING fix (item 2/4): admin walk-in exception on create_appointment ---


@pytest.mark.asyncio
async def test_create_appointment_walk_in_under_2h30_creates_confirmed_directly():
    """Admin-created walk-ins less than 2h30 out skip PENDING/negotiation
    entirely and are created straight to CONFIRMED -- there is no negotiation
    to time out, so no timer is needed and none is scheduled for this row."""
    admin = _staff_member()
    client = _booking_client()
    appt_repo = FakeAppointmentRepository()
    user_repo = FakeUserRepo(client=client, admin=admin)
    service = AppointmentManagement(
        appt_repo, user_repo, FakeStaffRepo(Staff(telegram_user_id=admin.telegram_user_id, clinic_id=1)),
        _clinic_repo(),
    )

    now = get_current_tashkent_datetime()
    walk_in_datetime = (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")

    appointment = await service.create_appointment(
        admin.telegram_user_id,
        {"phone": client.phone, "appointment_datetime": walk_in_datetime, "purpose": "Консультация"},
    )

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.created == [appointment]


@pytest.mark.asyncio
async def test_create_appointment_at_2h30_or_more_still_creates_pending():
    """Regression check: the walk-in exception must not swallow the normal
    admin-invite path -- a target a comfortable 3 hours out (well above 2h30)
    still creates PENDING exactly like before this fix."""
    admin = _staff_member()
    client = _booking_client()
    appt_repo = FakeAppointmentRepository()
    user_repo = FakeUserRepo(client=client, admin=admin)
    service = AppointmentManagement(
        appt_repo, user_repo, FakeStaffRepo(Staff(telegram_user_id=admin.telegram_user_id, clinic_id=1)),
        _clinic_repo(),
    )

    now = get_current_tashkent_datetime()
    invite_datetime = (now + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")

    appointment = await service.create_appointment(
        admin.telegram_user_id,
        {"phone": client.phone, "appointment_datetime": invite_datetime, "purpose": "Консультация"},
    )

    assert appointment.status is AppointmentStatus.PENDING
    assert appt_repo.created == [appointment]


# --- Zombie PENDING fix (item 3/4): cancellation cutoff stays decoupled ---


@pytest.mark.asyncio
async def test_cancellation_cutoff_stays_1h_independent_of_2h30_booking_threshold():
    """Key regression test: CANCELLATION_CUTOFF_HOURS (1h) must not have been
    accidentally re-coupled to the new MIN_LEAD_TIME (2h30) threshold (see the
    2026-07-16 decision in docs/zombie_pending_fix_prompt.md). A lead time of
    ~1h15 clears the 1h cancellation cutoff -- cancelling succeeds -- even
    though that exact same lead time sits inside the 2h30 zone that would
    reject a booking/reschedule request with BookingTooSoonError. Two
    independent rows are used so cancelling the first (which finalizes it)
    cannot interfere with the reschedule attempt on the second."""
    now = get_current_tashkent_datetime()
    lead_time = timedelta(hours=1, minutes=15)
    client = _owning_client()

    cancel_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + lead_time, status=AppointmentStatus.CONFIRMED)]
    )
    cancel_service = AppointmentManagement(cancel_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    cancelled = await cancel_service.cancel_appointment_by_client(1, client.telegram_user_id, enforce_cutoff=True)

    assert cancelled.status is AppointmentStatus.CANCELLED
    assert cancel_repo.status_updates == [(1, AppointmentStatus.CANCELLED)]

    reschedule_repo = FakeAppointmentRepository(
        [_appointment_at(2, now + timedelta(days=3), status=AppointmentStatus.CONFIRMED)]
    )
    reschedule_service = AppointmentManagement(
        reschedule_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo()
    )

    new_dt = (now + lead_time).strftime("%Y-%m-%d %H:%M")
    with pytest.raises(BookingTooSoonError):
        await reschedule_service.request_reschedule_by_client(2, client.telegram_user_id, new_dt)

    assert reschedule_repo.proposed_datetime_updates == []


