from datetime import timedelta

import pytest

from bot.exceptions.appointment_exceptions import (
    AppointmentAlreadyFinalizedError,
    AppointmentNotFoundError,
    CancellationWindowExpiredError,
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

    async def create_appointment(self, appointment):
        self.created.append(appointment)
        return appointment

    async def get_appointments_by_client_id(self, client_id):
        return [a for a in self.appointments if a.client_id == client_id]

    async def get_appointment_by_id(self, appointment_id):
        return next((a for a in self.appointments if a.id == appointment_id), None)

    async def appointment_exists(self, appointment_id):
        return any(a.id == appointment_id for a in self.appointments)

    async def delete_appointment(self, appointment_id):
        self.appointments = [a for a in self.appointments if a.id != appointment_id]

    async def update_appointment_status(self, appointment_id, status):
        self.status_updates.append((appointment_id, status))

    async def update_appointment(self, appointment_id, appointment):
        self.updated.append((appointment_id, appointment))


class FakeUserRepo:
    def __init__(self, client=None, admin=None):
        self.client = client
        self.admin = admin

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
    service = AppointmentManagement(
        appt_repo,
        FakeUserRepo(_client()),
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1)),
        _clinic_repo(),
    )

    appointment = await service.create_appointment(
        999,
        {"phone": "+998901234567", "appointment_datetime": "2026-07-10 14:30", "purpose": "Консультация"},
    )

    assert appt_repo.created == [appointment]
    assert appointment.clinic_id == 1
    assert appointment.client_id == 7
    assert appointment.clinic_name == "Зуб Мудрости"
    assert appointment.status is AppointmentStatus.PENDING
    assert appointment.created_by is CreatedBy.ADMIN


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


def _appointment_at(appointment_id, dt, client_id=7, status=AppointmentStatus.PENDING):
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        datetime=dt.strftime("%Y-%m-%d %H:%M:%S"),
        purpose="Консультация",
        created_by=CreatedBy.CLIENT,
        status=status,
        id=appointment_id,
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
    appt_repo = FakeAppointmentRepository([_appointment_at(1, now + timedelta(days=1))])
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
async def test_confirm_appointment_by_client_succeeds_from_pending():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.PENDING)]
    )
    client = _owning_client()
    service = AppointmentManagement(appt_repo, FakeUserRepo(client), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.confirm_appointment_by_client(1, client.telegram_user_id)

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CONFIRMED)]


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
async def test_cancel_appointment_by_client_blocked_within_2h_when_cutoff_enforced():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository([_appointment_at(1, now + timedelta(hours=1))])
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
async def test_cancel_appointment_by_client_allowed_outside_2h_window():
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
