import itertools
from datetime import date, datetime, timedelta
from unittest.mock import patch

import aiosqlite
import pytest

from bot.exceptions.appointment_exceptions import (
    AppointmentAlreadyDecidedError,
    AppointmentAlreadyFinalizedError,
    AppointmentNotFoundError,
    AwaitingClinicDecisionError,
    BookingTooSoonError,
    CancellationCooldownExceededError,
    CancellationWindowExpiredError,
    NegotiationInProgressError,
    NoPendingProposalError,
    PendingRequestLimitExceededError,
    SlotUnavailableError,
)
from bot.config.booking_config import (
    CANCELLATION_COOLDOWN_WINDOW_MINUTES,
    MAX_CANCELLATIONS_PER_COOLDOWN_WINDOW,
)
from bot.config.clinic_instances import STAFF_SEED_BY_INSTANCE
from bot.exceptions.user_exceptions import RoleError, UserNotFoundError
from bot.models.appointment import Appointment
from bot.models.appointment_notification import AppointmentNotification
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.staff_repository import StaffRepository
from bot.repositories.user_repository import UserRepository
from bot.repositories.user_settings_repository import UserSettingsRepository
from bot.services.appointment.appointment_management import (
    DUPLICATE_CLIENT_SLOT_MESSAGE,
    SLOT_UNAVAILABLE_MESSAGE,
    AppointmentManagement,
)
from bot.services.client.client_management import ClientManagement
from bot.services.utils.date_parser import get_current_tashkent_datetime
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role


FINALIZED_STATUSES = {
    AppointmentStatus.CANCELLED,
    AppointmentStatus.COMPLETED,
    AppointmentStatus.NO_SHOW,
    AppointmentStatus.EXPIRED,
}


class FakeAppointmentRepository:
    def __init__(self, appointments=None):
        self.appointments = list(appointments or [])
        self.created = []
        self.status_updates = []
        self.updated = []
        self.proposed_datetime_updates = []
        self.proposed_by_updates = []
        self.price_updates = []
        self.notifications: list[AppointmentNotification] = []

    async def create_appointment(self, appointment):
        self.created.append(appointment)
        return appointment

    async def get_appointments_by_client_id(self, client_id, clinic_id=None, doctor_id=None):
        return [a for a in self.appointments if a.client_id == client_id]

    async def get_appointment_by_id(self, appointment_id):
        return next((a for a in self.appointments if a.id == appointment_id), None)

    async def get_appointments_by_doctor_and_date(self, doctor_id, date, statuses: list[AppointmentStatus] | None = None):
        if statuses is None:
            return [
                a for a in self.appointments
                if a.doctor_id == doctor_id and a.datetime.startswith(date) and a.status == AppointmentStatus.CONFIRMED
            ]

        return [
            a for a in self.appointments
            if a.doctor_id == doctor_id and a.datetime.startswith(date) and a.status in statuses
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

    def _find(self, appointment_id):
        return next((a for a in self.appointments if a.id == appointment_id), None)

    async def try_confirm_or_reject_pending(self, appointment_id, new_status, decided_by_user_id, status_updated_at):
        # NOTE: deliberately does not mutate the shared Appointment object -- the
        # real repository only touches DB rows, never the caller's Python object.
        # AppointmentManagement always applies the equivalent in-memory field
        # updates itself afterward (using values captured before this call), so
        # mutating here too would risk clobbering a field the service re-reads
        # post-call (see accept_proposed_datetime/accept_client_reschedule below).
        appointment = self._find(appointment_id)
        if appointment is None:
            return False
        if appointment.status != AppointmentStatus.PENDING or appointment.proposed_datetime is not None:
            return False

        self.status_updates.append((appointment_id, new_status))
        return True

    async def try_propose_new_datetime(
        self, appointment_id, proposed_datetime, proposed_by, decided_by_user_id, expected_status
    ):
        appointment = self._find(appointment_id)
        if appointment is None:
            return False
        if appointment.status.value != expected_status:
            return False
        if appointment.proposed_datetime is not None and appointment.proposed_by == CreatedBy.ADMIN:
            return False

        self.proposed_datetime_updates.append((appointment_id, proposed_datetime))
        self.proposed_by_updates.append((appointment_id, CreatedBy(proposed_by)))
        return True

    async def try_resolve_client_reschedule(
        self, appointment_id, accept, decided_by_user_id, status_updated_at, new_datetime=None
    ):
        appointment = self._find(appointment_id)
        if appointment is None:
            return False
        if appointment.status in FINALIZED_STATUSES:
            return False
        if appointment.proposed_by != CreatedBy.CLIENT or appointment.proposed_datetime is None:
            return False

        self.proposed_datetime_updates.append((appointment_id, None))
        self.proposed_by_updates.append((appointment_id, None))

        if accept:
            self.updated.append((appointment_id, appointment))
        else:
            self.status_updates.append((appointment_id, AppointmentStatus.CANCELLED))

        return True

    async def try_complete_appointment(self, appointment_id, decided_by_user_id, status_updated_at):
        appointment = self._find(appointment_id)
        if appointment is None:
            return False
        if appointment.status in FINALIZED_STATUSES:
            return False

        self.status_updates.append((appointment_id, AppointmentStatus.COMPLETED))
        return True

    async def try_resolve_admin_proposal(self, appointment_id, accept, status_updated_at, new_datetime=None):
        appointment = self._find(appointment_id)
        if appointment is None:
            return False
        if appointment.status in FINALIZED_STATUSES:
            return False
        if appointment.proposed_by != CreatedBy.ADMIN or appointment.proposed_datetime is None:
            return False

        self.proposed_datetime_updates.append((appointment_id, None))
        self.proposed_by_updates.append((appointment_id, None))

        if accept:
            self.updated.append((appointment_id, appointment))
        else:
            self.status_updates.append((appointment_id, AppointmentStatus.CANCELLED))

        return True

    async def add_appointment_notification(self, appointment_id, chat_id, message_id, kind):
        self.notifications.append(
            AppointmentNotification(
                id=len(self.notifications) + 1,
                appointment_id=appointment_id,
                chat_id=chat_id,
                message_id=message_id,
                kind=kind,
            )
        )

    async def get_appointment_notifications(self, appointment_id, kind):
        return [n for n in self.notifications if n.appointment_id == appointment_id and n.kind == kind]


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

    async def get_client_by_phone_in_clinic(self, phone, clinic_id):
        if self.client and self.client.phone == phone and self.client.clinic_id == clinic_id:
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

    async def phone_exists(self, phone):
        return self.client is not None and self.client.phone == phone

    async def create_user(self, user):
        if user.ID is None:
            user.ID = 500  # simulates a DB-assigned cursor.lastrowid
        self.client = user


class FakeClientClinicRepo:
    def __init__(self):
        self.links = set()
        self.link_calls = []

    async def link_client_to_clinic(self, client_id, clinic_id):
        self.link_calls.append((client_id, clinic_id))
        self.links.add((client_id, clinic_id))

    async def client_linked_to_clinic(self, client_id, clinic_id):
        return (client_id, clinic_id) in self.links

    async def get_client_clinic_ids(self, client_id):
        return [cid for (uid, cid) in self.links if uid == client_id]


class FakeStaffRepo:
    def __init__(self, staff=None):
        self.staff = staff

    async def get_staff(self, telegram_user_id):
        if isinstance(self.staff, dict):
            return self.staff.get(telegram_user_id)
        return self.staff

    async def get_staff_by_clinic_id(self, clinic_id):
        if isinstance(self.staff, dict):
            return [s for s in self.staff.values() if s.clinic_id == clinic_id]
        if self.staff is not None and self.staff.clinic_id == clinic_id:
            return [self.staff]
        return []


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
    # telegram_user_id is set so this exercises the default PENDING path, not the
    # "client has no Telegram account -> auto-confirm" branch (covered separately).
    client = User(full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, ID=7, telegram_user_id=555)
    service = AppointmentManagement(
        appt_repo,
        FakeUserRepo(client, admin=admin),
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
async def test_create_appointment_auto_confirms_client_without_telegram_account():
    appt_repo = FakeAppointmentRepository()
    admin = User(full_name="Доктор", phone="+998900000000", role=Role.ADMIN, ID=42, telegram_user_id=999)
    service = AppointmentManagement(
        appt_repo,
        FakeUserRepo(_client(), admin=admin),  # _client() has no telegram_user_id
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1)),
        _clinic_repo(),
    )

    appointment = await service.create_appointment(
        999,
        {"phone": "+998901234567", "appointment_datetime": _future_datetime(), "purpose": "Консультация"},
    )

    assert appointment.status is AppointmentStatus.CONFIRMED


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
    """Reception/manager admins with is_doctor=False are not doctors and
    must not appear in the self-booking staff-selection keyboard."""
    client = _booking_client()
    own_scope_doctor = _staff_member(staff_id=99, telegram_user_id=999, full_name="Петров Петр")
    clinic_scope_admin = _staff_member(staff_id=100, telegram_user_id=1000, full_name="Артём Управляющий")
    user_repo = FakeUserRepo(client=client, staff_by_clinic={1: [own_scope_doctor, clinic_scope_admin]})
    staff_repo = FakeStaffRepo({
        999: Staff(telegram_user_id=999, clinic_id=1),
        1000: Staff(telegram_user_id=1000, clinic_id=1, visibility_scope="clinic", is_doctor=False),
    })
    service = AppointmentManagement(FakeAppointmentRepository(), user_repo, staff_repo, _clinic_repo())

    staff_list = await service.list_bookable_staff(client.telegram_user_id)

    assert staff_list == [own_scope_doctor]
    assert clinic_scope_admin not in staff_list


@pytest.mark.asyncio
async def test_list_bookable_staff_keeps_own_and_none_scope_admins():
    client = _booking_client()
    none_scope = _staff_member(staff_id=99, telegram_user_id=999, full_name="Петров Петр")
    own_scope = _staff_member(staff_id=101, telegram_user_id=1001, full_name="Елена Врач")
    user_repo = FakeUserRepo(client=client, staff_by_clinic={1: [none_scope, own_scope]})
    staff_repo = FakeStaffRepo({
        999: Staff(telegram_user_id=999, clinic_id=1),
        1001: Staff(telegram_user_id=1001, clinic_id=1, visibility_scope="own"),
    })
    service = AppointmentManagement(FakeAppointmentRepository(), user_repo, staff_repo, _clinic_repo())

    staff_list = await service.list_bookable_staff(client.telegram_user_id)

    assert staff_list == [none_scope, own_scope]


# --- resolve_admin_appointment_filter ---

def _admin_with_scope(scope: str | None, admin_id=42, telegram_user_id=999):
    admin = User(
        full_name="Петров Петр",
        phone="+998907654321",
        role=Role.ADMIN,
        telegram_user_id=telegram_user_id,
        ID=admin_id,
        clinic_id=1,
        clinic_name="Зуб Мудрости",
    )
    staff = Staff(telegram_user_id=telegram_user_id, clinic_id=1, visibility_scope=scope)

    return admin, staff


@pytest.mark.asyncio
async def test_resolve_admin_appointment_filter_none_scope_returns_own_admin_id():
    admin, staff = _admin_with_scope(None)
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(staff),
        _clinic_repo(),
    )

    clinic_id, doctor_id = await service.resolve_admin_appointment_filter(admin.telegram_user_id)

    assert (clinic_id, doctor_id) == (1, 42)


@pytest.mark.asyncio
async def test_resolve_admin_appointment_filter_own_scope_returns_own_admin_id():
    admin, staff = _admin_with_scope("own")
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(staff),
        _clinic_repo(),
    )

    clinic_id, doctor_id = await service.resolve_admin_appointment_filter(admin.telegram_user_id)

    assert (clinic_id, doctor_id) == (1, 42)


@pytest.mark.asyncio
async def test_resolve_admin_appointment_filter_clinic_scope_returns_no_doctor_filter():
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(staff),
        _clinic_repo(),
    )

    clinic_id, doctor_id = await service.resolve_admin_appointment_filter(admin.telegram_user_id)

    assert (clinic_id, doctor_id) == (1, None)


# --- list_clinic_doctors_for_creation ---

@pytest.mark.asyncio
async def test_list_clinic_doctors_for_creation_own_scope_returns_empty():
    admin, staff = _admin_with_scope("own")
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(staff),
        _clinic_repo(),
    )

    doctors = await service.list_clinic_doctors_for_creation(admin.telegram_user_id)

    assert doctors == []


@pytest.mark.asyncio
async def test_list_clinic_doctors_for_creation_none_scope_returns_empty():
    admin, staff = _admin_with_scope(None)
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(staff),
        _clinic_repo(),
    )

    doctors = await service.list_clinic_doctors_for_creation(admin.telegram_user_id)

    assert doctors == []


@pytest.mark.asyncio
async def test_list_clinic_doctors_for_creation_clinic_scope_filters_by_is_doctor_including_self():
    """Candidate filtering now follows is_doctor for every staff member, self
    included: the requesting admin's own visibility_scope only gates whether
    the picker is shown at all, it no longer force-includes them."""
    requesting_admin = _staff_member(staff_id=42, telegram_user_id=999, full_name="Артём Управляющий")
    doctor_colleague = _staff_member(staff_id=99, telegram_user_id=1000, full_name="Петров Петр")
    non_doctor_staff = _staff_member(staff_id=101, telegram_user_id=1001, full_name="Другой Управляющий")

    user_repo = FakeUserRepo(
        admin=requesting_admin,
        staff_by_clinic={1: [requesting_admin, doctor_colleague, non_doctor_staff]},
    )
    staff_repo = FakeStaffRepo({
        999: Staff(telegram_user_id=999, clinic_id=1, visibility_scope="clinic", is_doctor=True),
        1000: Staff(telegram_user_id=1000, clinic_id=1, visibility_scope="own", is_doctor=True),
        1001: Staff(telegram_user_id=1001, clinic_id=1, visibility_scope="clinic", is_doctor=False),
    })
    service = AppointmentManagement(FakeAppointmentRepository(), user_repo, staff_repo, _clinic_repo())

    doctors = await service.list_clinic_doctors_for_creation(requesting_admin.telegram_user_id)

    assert doctors == [requesting_admin, doctor_colleague]
    assert non_doctor_staff not in doctors


@pytest.mark.asyncio
async def test_list_clinic_doctors_for_creation_excludes_self_when_not_a_doctor():
    """The old 'always keep self' carve-out is dropped: a requesting admin
    with is_doctor=False is excluded from the picker just like anyone else,
    even though their own visibility_scope='clinic' still opens the picker."""
    requesting_admin = _staff_member(staff_id=42, telegram_user_id=999, full_name="Артём Управляющий")
    doctor_colleague = _staff_member(staff_id=99, telegram_user_id=1000, full_name="Петров Петр")

    user_repo = FakeUserRepo(
        admin=requesting_admin,
        staff_by_clinic={1: [requesting_admin, doctor_colleague]},
    )
    staff_repo = FakeStaffRepo({
        999: Staff(telegram_user_id=999, clinic_id=1, visibility_scope="clinic", is_doctor=False),
        1000: Staff(telegram_user_id=1000, clinic_id=1, visibility_scope="own", is_doctor=True),
    })
    service = AppointmentManagement(FakeAppointmentRepository(), user_repo, staff_repo, _clinic_repo())

    doctors = await service.list_clinic_doctors_for_creation(requesting_admin.telegram_user_id)

    assert doctors == [doctor_colleague]
    assert requesting_admin not in doctors


@pytest.mark.asyncio
async def test_list_clinic_doctors_for_creation_clinic_scope_shows_picker_with_single_doctor():
    requesting_admin = _staff_member(staff_id=42, telegram_user_id=999, full_name="Артём Управляющий")

    user_repo = FakeUserRepo(admin=requesting_admin, staff_by_clinic={1: [requesting_admin]})
    staff_repo = FakeStaffRepo({
        999: Staff(telegram_user_id=999, clinic_id=1, visibility_scope="clinic", is_doctor=True),
    })
    service = AppointmentManagement(FakeAppointmentRepository(), user_repo, staff_repo, _clinic_repo())

    doctors = await service.list_clinic_doctors_for_creation(requesting_admin.telegram_user_id)

    assert doctors == [requesting_admin]


# --- create_appointment with an explicitly chosen doctor ---

@pytest.mark.asyncio
async def test_create_appointment_uses_chosen_doctor_when_staff_user_id_present():
    """Choosing another doctor is the 'clinic'-scope (dispatcher/manager) flow --
    the acting admin's own staff record must reflect that scope."""
    appt_repo = FakeAppointmentRepository()
    admin = User(full_name="Управляющий", phone="+998900000000", role=Role.ADMIN, ID=42, telegram_user_id=999)
    chosen_doctor = User(full_name="Петров Петр", phone="+998907654321", role=Role.ADMIN, ID=99, telegram_user_id=1000, clinic_id=1)
    user_repo = FakeUserRepo(_client(), admin=admin, users_by_id={99: chosen_doctor})
    service = AppointmentManagement(
        appt_repo,
        user_repo,
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1, visibility_scope="clinic")),
        _clinic_repo(),
    )

    appointment = await service.create_appointment(
        999,
        {
            "phone": "+998901234567",
            "appointment_datetime": _future_datetime(),
            "purpose": "Консультация",
            "staff_user_id": 99,
        },
    )

    assert appointment.doctor_id == 99


@pytest.mark.asyncio
async def test_create_appointment_raises_when_chosen_doctor_not_found():
    appt_repo = FakeAppointmentRepository()
    admin = User(full_name="Управляющий", phone="+998900000000", role=Role.ADMIN, ID=42, telegram_user_id=999)
    user_repo = FakeUserRepo(_client(), admin=admin, users_by_id={})
    service = AppointmentManagement(
        appt_repo,
        user_repo,
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1, visibility_scope="clinic")),
        _clinic_repo(),
    )

    with pytest.raises(UserNotFoundError):
        await service.create_appointment(
            999,
            {
                "phone": "+998901234567",
                "appointment_datetime": _future_datetime(),
                "purpose": "Консультация",
                "staff_user_id": 404,
            },
        )


@pytest.mark.asyncio
async def test_create_appointment_rejects_doctor_from_another_clinic():
    appt_repo = FakeAppointmentRepository()
    admin = User(full_name="Управляющий", phone="+998900000000", role=Role.ADMIN, ID=42, telegram_user_id=999)
    other_clinic_doctor = User(
        full_name="Петров Петр", phone="+998907654321", role=Role.ADMIN, ID=99, telegram_user_id=1000, clinic_id=2
    )
    user_repo = FakeUserRepo(_client(), admin=admin, users_by_id={99: other_clinic_doctor})
    service = AppointmentManagement(
        appt_repo,
        user_repo,
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1, visibility_scope="clinic")),
        _clinic_repo(),
    )

    with pytest.raises(UserNotFoundError):
        await service.create_appointment(
            999,
            {
                "phone": "+998901234567",
                "appointment_datetime": _future_datetime(),
                "purpose": "Консультация",
                "staff_user_id": 99,
            },
        )


@pytest.mark.asyncio
async def test_create_appointment_rejects_own_scope_admin_assigning_another_doctor():
    """An 'own'-scope doctor has no legitimate way to reach staff_user_id != self
    through the UI (the doctor picker is never shown to them), but the service
    itself must reject it too -- not just rely on the handler/FSM never offering it."""
    appt_repo = FakeAppointmentRepository()
    admin = User(full_name="Петров Петр", phone="+998900000000", role=Role.ADMIN, ID=42, telegram_user_id=999)
    colleague = User(
        full_name="Иванова Анна", phone="+998907654321", role=Role.ADMIN, ID=99, telegram_user_id=1000, clinic_id=1
    )
    user_repo = FakeUserRepo(_client(), admin=admin, users_by_id={99: colleague})
    service = AppointmentManagement(
        appt_repo,
        user_repo,
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1, visibility_scope="own")),
        _clinic_repo(),
    )

    with pytest.raises(UserNotFoundError):
        await service.create_appointment(
            999,
            {
                "phone": "+998901234567",
                "appointment_datetime": _future_datetime(),
                "purpose": "Консультация",
                "staff_user_id": 99,
            },
        )


@pytest.mark.asyncio
async def test_create_appointment_allows_own_scope_admin_assigning_to_self():
    """staff_user_id pointing back at the acting admin's own ID must never be
    blocked by the scope check -- only assigning to someone ELSE requires
    'clinic' scope."""
    appt_repo = FakeAppointmentRepository()
    admin = User(full_name="Петров Петр", phone="+998900000000", role=Role.ADMIN, ID=42, telegram_user_id=999, clinic_id=1)
    user_repo = FakeUserRepo(_client(), admin=admin, users_by_id={42: admin})
    service = AppointmentManagement(
        appt_repo,
        user_repo,
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1, visibility_scope="own")),
        _clinic_repo(),
    )

    appointment = await service.create_appointment(
        999,
        {
            "phone": "+998901234567",
            "appointment_datetime": _future_datetime(),
            "purpose": "Консультация",
            "staff_user_id": 42,
        },
    )

    assert appointment.doctor_id == 42


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
    admin, staff = _admin_with_scope("own")
    other_doctor_appointment = _appointment_with_doctor(clinic_id=1, doctor_id=777)
    service = AppointmentManagement(
        FakeAppointmentRepository([other_doctor_appointment]),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(staff),
        _clinic_repo(),
    )

    result = await service.get_appointment_for_admin(
        other_doctor_appointment.id, admin.telegram_user_id
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_appointment_for_admin_own_scope_blocks_other_clinic():
    admin, staff = _admin_with_scope("own")
    other_clinic_appointment = _appointment_with_doctor(clinic_id=2, doctor_id=admin.ID)
    service = AppointmentManagement(
        FakeAppointmentRepository([other_clinic_appointment]),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(staff),
        _clinic_repo(),
    )

    result = await service.get_appointment_for_admin(
        other_clinic_appointment.id, admin.telegram_user_id
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_appointment_for_admin_own_scope_allows_own_appointment():
    admin, staff = _admin_with_scope("own")
    own_appointment = _appointment_with_doctor(clinic_id=1, doctor_id=admin.ID)
    service = AppointmentManagement(
        FakeAppointmentRepository([own_appointment]),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(staff),
        _clinic_repo(),
    )

    result = await service.get_appointment_for_admin(own_appointment.id, admin.telegram_user_id)

    assert result is own_appointment


@pytest.mark.asyncio
async def test_get_appointment_for_admin_clinic_scope_allows_any_doctor_same_clinic():
    admin, staff = _admin_with_scope("clinic")
    other_doctor_appointment = _appointment_with_doctor(clinic_id=1, doctor_id=777)
    service = AppointmentManagement(
        FakeAppointmentRepository([other_doctor_appointment]),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(staff),
        _clinic_repo(),
    )

    result = await service.get_appointment_for_admin(
        other_doctor_appointment.id, admin.telegram_user_id
    )

    assert result is other_doctor_appointment


@pytest.mark.asyncio
async def test_get_appointment_for_admin_clinic_scope_blocks_other_clinic():
    admin, staff = _admin_with_scope("clinic")
    other_clinic_appointment = _appointment_with_doctor(clinic_id=2, doctor_id=777)
    service = AppointmentManagement(
        FakeAppointmentRepository([other_clinic_appointment]),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(staff),
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
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(
        FakeAppointmentRepository([]),
        FakeUserRepo(admin=admin),
        FakeStaffRepo(staff),
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


def _self_booked_appointment(
    appointment_id=1,
    client_id=7,
    status=AppointmentStatus.PENDING,
    proposed_datetime=None,
    status_updated_at=None,
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
        status_updated_at=status_updated_at,
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


# --- Cancellation cooldown throttle tests ---
#
# A client capped at MAX_CANCELLATIONS_PER_COOLDOWN_WINDOW client-created
# CANCELLED transitions within CANCELLATION_COOLDOWN_WINDOW_MINUTES; a further
# create_self_booking attempt must raise before any DB write. Time is frozen
# via patching get_current_tashkent_datetime, mirroring the MIN_LEAD_TIME
# boundary tests above, so counts never depend on wall-clock timing.


def _admin_cancelled_appointment(appointment_id, client_id, status_updated_at):
    """A CANCELLED appointment created by admin (not client) -- used to prove
    admin-created cancellations are excluded from the client's cooldown count."""
    return Appointment(
        clinic_id=1,
        client_id=client_id,
        datetime="2026-07-10 14:30",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.CANCELLED,
        id=appointment_id,
        status_updated_at=status_updated_at,
    )


@pytest.mark.asyncio
async def test_create_self_booking_raises_when_cancellation_cooldown_exceeded():
    client = _booking_client()
    staff = _staff_member()
    base = get_current_tashkent_datetime().replace(second=0, microsecond=0)

    with patch(
        "bot.services.appointment.appointment_management.get_current_tashkent_datetime",
        return_value=base,
    ):
        recent = (base - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        appt_repo = FakeAppointmentRepository([
            _self_booked_appointment(1, client.ID, AppointmentStatus.CANCELLED, status_updated_at=recent),
            _self_booked_appointment(2, client.ID, AppointmentStatus.CANCELLED, status_updated_at=recent),
            _self_booked_appointment(3, client.ID, AppointmentStatus.CANCELLED, status_updated_at=recent),
        ])
        user_repo = FakeUserRepo(client=client, users_by_id={staff.ID: staff})
        service = AppointmentManagement(appt_repo, user_repo, FakeStaffRepo(None), _clinic_repo())
        target = (base + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")

        with pytest.raises(CancellationCooldownExceededError):
            await service.create_self_booking(
                client.telegram_user_id,
                {"staff_user_id": staff.ID, "appointment_datetime": target, "complaint": "Болит зуб"},
            )

    assert appt_repo.created == []


@pytest.mark.asyncio
async def test_create_self_booking_allows_when_cancellations_below_limit():
    """2 recent cancellations is below the MAX_CANCELLATIONS_PER_COOLDOWN_WINDOW
    threshold of 3 -- the check is strictly '>=', so 2 must be allowed."""
    client = _booking_client()
    staff = _staff_member()
    base = get_current_tashkent_datetime().replace(second=0, microsecond=0)

    with patch(
        "bot.services.appointment.appointment_management.get_current_tashkent_datetime",
        return_value=base,
    ):
        recent = (base - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        appt_repo = FakeAppointmentRepository([
            _self_booked_appointment(1, client.ID, AppointmentStatus.CANCELLED, status_updated_at=recent),
            _self_booked_appointment(2, client.ID, AppointmentStatus.CANCELLED, status_updated_at=recent),
        ])
        user_repo = FakeUserRepo(client=client, users_by_id={staff.ID: staff})
        service = AppointmentManagement(appt_repo, user_repo, FakeStaffRepo(None), _clinic_repo())
        target = (base + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")

        appointment = await service.create_self_booking(
            client.telegram_user_id,
            {"staff_user_id": staff.ID, "appointment_datetime": target, "complaint": "Болит зуб"},
        )

    assert appointment.status is AppointmentStatus.PENDING
    assert appt_repo.created == [appointment]


@pytest.mark.asyncio
async def test_create_self_booking_raises_when_cancellation_is_just_under_window():
    """A cancellation 4m59s ago is still inside the 5-minute window and must
    count, tipping 2 older cancellations plus this one over the limit."""
    client = _booking_client()
    staff = _staff_member()
    base = get_current_tashkent_datetime().replace(second=0, microsecond=0)

    with patch(
        "bot.services.appointment.appointment_management.get_current_tashkent_datetime",
        return_value=base,
    ):
        recent = (base - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        just_under_window = (
            base - timedelta(minutes=CANCELLATION_COOLDOWN_WINDOW_MINUTES) + timedelta(seconds=1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        appt_repo = FakeAppointmentRepository([
            _self_booked_appointment(1, client.ID, AppointmentStatus.CANCELLED, status_updated_at=recent),
            _self_booked_appointment(2, client.ID, AppointmentStatus.CANCELLED, status_updated_at=recent),
            _self_booked_appointment(3, client.ID, AppointmentStatus.CANCELLED, status_updated_at=just_under_window),
        ])
        user_repo = FakeUserRepo(client=client, users_by_id={staff.ID: staff})
        service = AppointmentManagement(appt_repo, user_repo, FakeStaffRepo(None), _clinic_repo())
        target = (base + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")

        with pytest.raises(CancellationCooldownExceededError):
            await service.create_self_booking(
                client.telegram_user_id,
                {"staff_user_id": staff.ID, "appointment_datetime": target, "complaint": "Болит зуб"},
            )

    assert appt_repo.created == []


@pytest.mark.asyncio
async def test_create_self_booking_ignores_cancellation_exactly_at_window_boundary():
    """A cancellation exactly CANCELLATION_COOLDOWN_WINDOW_MINUTES ago is
    excluded (strict '<' comparison), so only 2 recent ones remain counted
    and the booking must succeed."""
    client = _booking_client()
    staff = _staff_member()
    base = get_current_tashkent_datetime().replace(second=0, microsecond=0)

    with patch(
        "bot.services.appointment.appointment_management.get_current_tashkent_datetime",
        return_value=base,
    ):
        recent = (base - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        at_boundary = (base - timedelta(minutes=CANCELLATION_COOLDOWN_WINDOW_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        appt_repo = FakeAppointmentRepository([
            _self_booked_appointment(1, client.ID, AppointmentStatus.CANCELLED, status_updated_at=recent),
            _self_booked_appointment(2, client.ID, AppointmentStatus.CANCELLED, status_updated_at=recent),
            _self_booked_appointment(3, client.ID, AppointmentStatus.CANCELLED, status_updated_at=at_boundary),
        ])
        user_repo = FakeUserRepo(client=client, users_by_id={staff.ID: staff})
        service = AppointmentManagement(appt_repo, user_repo, FakeStaffRepo(None), _clinic_repo())
        target = (base + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")

        appointment = await service.create_self_booking(
            client.telegram_user_id,
            {"staff_user_id": staff.ID, "appointment_datetime": target, "complaint": "Болит зуб"},
        )

    assert appointment.status is AppointmentStatus.PENDING
    assert appt_repo.created == [appointment]


@pytest.mark.asyncio
async def test_create_self_booking_ignores_admin_created_cancellations():
    client = _booking_client()
    staff = _staff_member()
    base = get_current_tashkent_datetime().replace(second=0, microsecond=0)

    with patch(
        "bot.services.appointment.appointment_management.get_current_tashkent_datetime",
        return_value=base,
    ):
        recent = (base - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        appt_repo = FakeAppointmentRepository([
            _admin_cancelled_appointment(1, client.ID, recent),
            _admin_cancelled_appointment(2, client.ID, recent),
            _admin_cancelled_appointment(3, client.ID, recent),
        ])
        user_repo = FakeUserRepo(client=client, users_by_id={staff.ID: staff})
        service = AppointmentManagement(appt_repo, user_repo, FakeStaffRepo(None), _clinic_repo())
        target = (base + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")

        appointment = await service.create_self_booking(
            client.telegram_user_id,
            {"staff_user_id": staff.ID, "appointment_datetime": target, "complaint": "Болит зуб"},
        )

    assert appointment.status is AppointmentStatus.PENDING
    assert appt_repo.created == [appointment]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED, AppointmentStatus.EXPIRED],
)
async def test_create_self_booking_ignores_non_cancelled_statuses(status):
    """Finalized-but-not-CANCELLED self-bookings (even with a recent
    status_updated_at) must never count toward the cooldown."""
    client = _booking_client()
    staff = _staff_member()
    base = get_current_tashkent_datetime().replace(second=0, microsecond=0)

    with patch(
        "bot.services.appointment.appointment_management.get_current_tashkent_datetime",
        return_value=base,
    ):
        recent = (base - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        appt_repo = FakeAppointmentRepository([
            _self_booked_appointment(1, client.ID, status, status_updated_at=recent),
            _self_booked_appointment(2, client.ID, status, status_updated_at=recent),
            _self_booked_appointment(3, client.ID, status, status_updated_at=recent),
        ])
        user_repo = FakeUserRepo(client=client, users_by_id={staff.ID: staff})
        service = AppointmentManagement(appt_repo, user_repo, FakeStaffRepo(None), _clinic_repo())
        target = (base + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")

        appointment = await service.create_self_booking(
            client.telegram_user_id,
            {"staff_user_id": staff.ID, "appointment_datetime": target, "complaint": "Болит зуб"},
        )

    assert appointment.status is AppointmentStatus.PENDING
    assert appt_repo.created == [appointment]


@pytest.mark.asyncio
async def test_cancellation_cooldown_also_counts_admin_rejected_requests():
    """Known, accepted tradeoff: an admin-rejected self-booking also
    transitions to CANCELLED via update_status, so it counts toward the same
    cooldown as a client-initiated cancellation. This is intentional -- the
    throttle keys purely on (created_by == CLIENT, status == CANCELLED,
    status_updated_at), not on which actor/code path produced that state."""
    client = _booking_client()
    staff = _staff_member()
    base = get_current_tashkent_datetime().replace(second=0, microsecond=0)

    with patch(
        "bot.services.appointment.appointment_management.get_current_tashkent_datetime",
        return_value=base,
    ):
        recent = (base - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        appt_repo = FakeAppointmentRepository([
            _self_booked_appointment(1, client.ID, AppointmentStatus.CANCELLED, status_updated_at=recent),
            _self_booked_appointment(2, client.ID, AppointmentStatus.CANCELLED, status_updated_at=recent),
            _self_booked_appointment(3, client.ID, AppointmentStatus.CANCELLED, status_updated_at=recent),
        ])
        user_repo = FakeUserRepo(client=client, users_by_id={staff.ID: staff})
        service = AppointmentManagement(appt_repo, user_repo, FakeStaffRepo(None), _clinic_repo())
        target = (base + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")

        with pytest.raises(CancellationCooldownExceededError):
            await service.create_self_booking(
                client.telegram_user_id,
                {"staff_user_id": staff.ID, "appointment_datetime": target, "complaint": "Болит зуб"},
            )

    assert appt_repo.created == []


@pytest.mark.asyncio
async def test_find_client_by_phone_without_clinic_id_uses_global_lookup():
    client = User(full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, ID=7, clinic_id=1)
    service = AppointmentManagement(
        FakeAppointmentRepository([]), FakeUserRepo(client=client), FakeStaffRepo(None), _clinic_repo(),
    )

    found = await service.find_client_by_phone("+998901234567")

    assert found is client


@pytest.mark.asyncio
async def test_find_client_by_phone_with_clinic_id_excludes_other_clinics():
    client = User(full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, ID=7, clinic_id=1)
    service = AppointmentManagement(
        FakeAppointmentRepository([]), FakeUserRepo(client=client), FakeStaffRepo(None), _clinic_repo(),
    )

    found_same_clinic = await service.find_client_by_phone("+998901234567", clinic_id=1)
    found_other_clinic = await service.find_client_by_phone("+998901234567", clinic_id=2)

    assert found_same_clinic is client
    assert found_other_clinic is None


@pytest.mark.asyncio
async def test_create_appointment_links_existing_client_to_new_clinic():
    """Client belongs to clinic 2 ("home" clinic), but an admin from clinic 1 books
    them. This is the dead-end scenario: the client must get auto-linked to clinic 1
    and the appointment must proceed without any PhoneAlreadyExistsError dead end."""
    appt_repo = FakeAppointmentRepository()
    admin = User(full_name="Доктор", phone="+998900000000", role=Role.ADMIN, ID=42, telegram_user_id=999)
    client = User(
        full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, ID=7,
        telegram_user_id=555, clinic_id=2,
    )
    client_clinic_repo = FakeClientClinicRepo()
    service = AppointmentManagement(
        appt_repo,
        FakeUserRepo(client, admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1)),
        _clinic_repo(clinic_id=1),
        client_clinic_repository=client_clinic_repo,
    )

    appointment = await service.create_appointment(
        999,
        {"phone": "+998901234567", "appointment_datetime": _future_datetime(), "purpose": "Консультация"},
    )

    assert appointment.clinic_id == 1
    assert appointment.client_id == 7
    assert await client_clinic_repo.client_linked_to_clinic(7, 1) is True


@pytest.mark.asyncio
async def test_create_appointment_link_is_safe_when_client_already_linked():
    appt_repo = FakeAppointmentRepository()
    admin = User(full_name="Доктор", phone="+998900000000", role=Role.ADMIN, ID=42, telegram_user_id=999)
    client = User(
        full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, ID=7,
        telegram_user_id=555, clinic_id=1,
    )
    client_clinic_repo = FakeClientClinicRepo()
    await client_clinic_repo.link_client_to_clinic(7, 1)
    service = AppointmentManagement(
        appt_repo,
        FakeUserRepo(client, admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1)),
        _clinic_repo(clinic_id=1),
        client_clinic_repository=client_clinic_repo,
    )

    appointment = await service.create_appointment(
        999,
        {"phone": "+998901234567", "appointment_datetime": _future_datetime(), "purpose": "Консультация"},
    )

    assert appointment.client_id == 7
    assert await client_clinic_repo.client_linked_to_clinic(7, 1) is True


@pytest.mark.asyncio
async def test_check_or_create_client_links_existing_client_to_requesting_clinic():
    admin = User(full_name="Доктор", phone="+998900000000", role=Role.ADMIN, ID=42, telegram_user_id=999)
    client = User(
        full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, ID=7, clinic_id=2,
    )
    client_clinic_repo = FakeClientClinicRepo()
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(client, admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1)),
        _clinic_repo(clinic_id=1),
        client_clinic_repository=client_clinic_repo,
    )

    result = await service.check_or_create_client(999, "Иванов Иван", "+998901234567")

    assert result is client
    assert await client_clinic_repo.client_linked_to_clinic(7, 1) is True


@pytest.mark.asyncio
async def test_check_or_create_client_creates_and_links_new_client():
    admin = User(full_name="Доктор", phone="+998900000000", role=Role.ADMIN, ID=42, telegram_user_id=999)
    client_clinic_repo = FakeClientClinicRepo()
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(client=None, admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1)),
        _clinic_repo(clinic_id=1),
        client_clinic_repository=client_clinic_repo,
    )

    new_client = await service.check_or_create_client(999, "Петров Петр", "+998907654321")

    assert new_client.full_name == "Петров Петр"
    assert new_client.phone == "+998907654321"
    assert new_client.ID is not None
    assert await client_clinic_repo.client_linked_to_clinic(new_client.ID, 1) is True


@pytest.mark.asyncio
async def test_check_or_create_client_creates_and_links_new_client_via_client_management():
    """Covers the ClientManagement-delegated branch, which is what actually runs in
    production (run.py always wires client_management) -- the inline fallback tested
    above is explicitly documented as "shouldn't happen in production"."""
    admin = User(full_name="Доктор", phone="+998900000000", role=Role.ADMIN, ID=42, telegram_user_id=999)
    user_repo = FakeUserRepo(client=None, admin=admin)
    client_clinic_repo = FakeClientClinicRepo()
    client_management = ClientManagement(
        user_repo, FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1)), _clinic_repo(clinic_id=1),
    )
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        user_repo,
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1)),
        _clinic_repo(clinic_id=1),
        client_management=client_management,
        client_clinic_repository=client_clinic_repo,
    )

    new_client = await service.check_or_create_client(999, "Петров Петр", "+998907654321")

    assert new_client.full_name == "Петров Петр"
    assert new_client.ID is not None
    assert await client_clinic_repo.client_linked_to_clinic(new_client.ID, 1) is True


@pytest.mark.asyncio
async def test_check_or_create_client_without_repository_wired_behaves_as_before():
    admin = User(full_name="Доктор", phone="+998900000000", role=Role.ADMIN, ID=42, telegram_user_id=999)
    client = User(
        full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, ID=7, clinic_id=2,
    )
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(client, admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1)),
        _clinic_repo(clinic_id=1),
    )

    result = await service.check_or_create_client(999, "Иванов Иван", "+998901234567")

    assert result is client

    new_client_service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeUserRepo(client=None, admin=admin),
        FakeStaffRepo(Staff(telegram_user_id=999, clinic_id=1)),
        _clinic_repo(clinic_id=1),
    )

    new_client = await new_client_service.check_or_create_client(999, "Петров Петр", "+998907654321")

    assert new_client.full_name == "Петров Петр"


@pytest.mark.asyncio
async def test_update_status():
    appt = _appointment()
    appt_repo = FakeAppointmentRepository([appt])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.update_status(appt, AppointmentStatus.CONFIRMED)

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CONFIRMED)]


@pytest.mark.asyncio
async def test_delete_appointment_removes_row():
    appt = _appointment()
    appt_repo = FakeAppointmentRepository([appt])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    await service.delete_appointment(appt)

    assert appt_repo.appointments == []


@pytest.mark.asyncio
async def test_delete_appointment_raises_when_already_deleted():
    """Guards the second racer in a concurrent double-delete: the row is gone
    by the time this call runs, so it must raise instead of silently
    succeeding and letting the caller send a duplicate cancellation notice."""
    appt = _appointment()
    appt_repo = FakeAppointmentRepository([appt])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())
    appt_repo.appointments = []

    with pytest.raises(AppointmentNotFoundError):
        await service.delete_appointment(appt)


@pytest.mark.asyncio
async def test_update_price_validates_and_persists():
    appt = _appointment()
    appt_repo = FakeAppointmentRepository([appt])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    appointment = await service.update_price(appt, 150000.0)

    assert appointment.price == 150000.0
    assert appt_repo.price_updates == [(1, 150000.0)]


@pytest.mark.asyncio
async def test_update_price_rejects_negative_price():
    from bot.exceptions.appointment_exceptions import InvalidPriceError

    appt = _appointment()
    appt_repo = FakeAppointmentRepository([appt])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(InvalidPriceError):
        await service.update_price(appt, -100.0)


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
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

    appointment = await service.confirm_pending_request(1, staff_telegram_id=999)

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CONFIRMED)]


@pytest.mark.asyncio
async def test_confirm_pending_request_blocked_when_proposal_pending():
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(proposed_datetime="2026-07-11 10:00")]
    )
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

    with pytest.raises(NegotiationInProgressError):
        await service.confirm_pending_request(1, staff_telegram_id=999)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_confirm_pending_request_raises_when_finalized():
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(status=AppointmentStatus.EXPIRED)]
    )
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.confirm_pending_request(1, staff_telegram_id=999)


@pytest.mark.asyncio
async def test_confirm_pending_request_raises_when_admin_from_different_clinic():
    """Regression guard: a staff_telegram_id resolving to an admin of another
    clinic must not be able to act on this appointment via a forged/replayed
    appointment_id, even though the id itself exists."""
    appt_repo = FakeAppointmentRepository([_pending_client_request()])
    admin, staff = _admin_with_scope("clinic")
    admin.clinic_id = 2
    staff.clinic_id = 2
    service = AppointmentManagement(
        appt_repo, FakeUserRepo(_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo(clinic_id=2)
    )

    with pytest.raises(AppointmentNotFoundError):
        await service.confirm_pending_request(1, staff_telegram_id=999)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_reject_pending_request_updates_status():
    appt_repo = FakeAppointmentRepository([_pending_client_request()])
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

    appointment = await service.reject_pending_request(1, staff_telegram_id=999)

    assert appointment.status is AppointmentStatus.CANCELLED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CANCELLED)]


@pytest.mark.asyncio
async def test_reject_pending_request_blocked_when_proposal_pending():
    appt_repo = FakeAppointmentRepository(
        [_pending_client_request(proposed_datetime="2026-07-11 10:00")]
    )
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

    with pytest.raises(NegotiationInProgressError):
        await service.reject_pending_request(1, staff_telegram_id=999)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_propose_new_datetime_sets_proposed_without_touching_status_or_datetime():
    appt_repo = FakeAppointmentRepository([_pending_client_request()])
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())
    proposed_datetime = _future_datetime(days=3, time_str="10:00")

    appointment = await service.propose_new_datetime(
        1, staff_telegram_id=999, proposed_datetime=proposed_datetime, kind="booking"
    )

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
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

    with pytest.raises(NegotiationInProgressError):
        await service.propose_new_datetime(
            1, staff_telegram_id=999, proposed_datetime="2026-07-12 10:00", kind="booking"
        )

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
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

    appointment = await service.propose_new_datetime(
        1, staff_telegram_id=999, proposed_datetime=new_proposed_datetime, kind="reschedule"
    )

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
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

    appointment = await service.propose_new_datetime(
        1, staff_telegram_id=999, proposed_datetime=proposed_datetime, kind="reschedule"
    )

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
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

    with pytest.raises(AppointmentAlreadyFinalizedError):
        await service.propose_new_datetime(
            1, staff_telegram_id=999, proposed_datetime="2026-07-11 10:00", kind="booking"
        )


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
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

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
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

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
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

    with pytest.raises(NoPendingProposalError):
        await service.accept_client_reschedule(1, staff_telegram_id=999)


@pytest.mark.asyncio
async def test_accept_client_reschedule_raises_when_no_proposal():
    now = get_current_tashkent_datetime()
    appt_repo = FakeAppointmentRepository(
        [_appointment_at(1, now + timedelta(days=1), status=AppointmentStatus.CONFIRMED)]
    )
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

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
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

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
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

    with pytest.raises(NoPendingProposalError):
        await service.reject_client_reschedule(1, staff_telegram_id=999)


# --- AppointmentAlreadyDecidedError (atomic race-closing on broadcast decisions) ---
#
# Simulates two staff members racing on the same broadcast: by the time this
# staff's decision reaches the repository, another admin already won the race
# (status/proposal fields already flipped, decided_by_user_id already
# recorded). The atomic try_* guard returns False and the service must raise
# AppointmentAlreadyDecidedError, attributing the decision to whoever
# actually won via resolve_decision_label.


def _winning_admin():
    return User(
        full_name="Иванова Анна",
        phone="+998907654322",
        role=Role.ADMIN,
        telegram_user_id=2000,
        ID=55,
        clinic_id=1,
        clinic_name="Зуб Мудрости",
    )


@pytest.mark.asyncio
async def test_confirm_pending_request_raises_already_decided_when_race_lost():
    winner = _winning_admin()
    already_decided = _pending_client_request()
    already_decided.status = AppointmentStatus.CONFIRMED
    already_decided.decided_by_user_id = winner.ID
    appt_repo = FakeAppointmentRepository([already_decided])
    admin, staff = _admin_with_scope("clinic")
    user_repo = FakeUserRepo(_client(), admin=admin, users_by_id={winner.ID: winner})
    staff_repo = FakeStaffRepo({
        999: staff,
        winner.telegram_user_id: Staff(telegram_user_id=winner.telegram_user_id, clinic_id=1, visibility_scope="clinic"),
    })
    service = AppointmentManagement(appt_repo, user_repo, staff_repo, _clinic_repo())

    with pytest.raises(AppointmentAlreadyDecidedError, match="Иванова Анна"):
        await service.confirm_pending_request(1, staff_telegram_id=999)


@pytest.mark.asyncio
async def test_reject_pending_request_raises_already_decided_when_race_lost():
    """Status is CONFIRMED (not CANCELLED): reject_pending_request calls
    _ensure_not_finalized() before ever reaching the atomic repository call,
    so a CANCELLED row would raise AppointmentAlreadyFinalizedError instead --
    CONFIRMED is the realistic "someone else already decided it" state that
    actually reaches and fails the try_confirm_or_reject_pending guard."""
    winner = _winning_admin()
    already_decided = _pending_client_request()
    already_decided.status = AppointmentStatus.CONFIRMED
    already_decided.decided_by_user_id = winner.ID
    appt_repo = FakeAppointmentRepository([already_decided])
    admin, staff = _admin_with_scope("clinic")
    user_repo = FakeUserRepo(_client(), admin=admin, users_by_id={winner.ID: winner})
    staff_repo = FakeStaffRepo({
        999: staff,
        winner.telegram_user_id: Staff(telegram_user_id=winner.telegram_user_id, clinic_id=1, visibility_scope="own"),
    })
    service = AppointmentManagement(appt_repo, user_repo, staff_repo, _clinic_repo())

    with pytest.raises(AppointmentAlreadyDecidedError, match="Доктор Иванова Анна"):
        await service.reject_pending_request(1, staff_telegram_id=999)


@pytest.mark.asyncio
async def test_complete_appointment_by_admin_raises_already_decided_when_race_lost():
    winner = _winning_admin()
    already_decided = _appointment_with_doctor(clinic_id=1, doctor_id=42)
    already_decided.status = AppointmentStatus.COMPLETED
    already_decided.decided_by_user_id = winner.ID
    appt_repo = FakeAppointmentRepository([already_decided])
    admin, staff = _admin_with_scope("own")
    user_repo = FakeUserRepo(admin=admin, users_by_id={winner.ID: winner})
    staff_repo = FakeStaffRepo(staff)
    service = AppointmentManagement(appt_repo, user_repo, staff_repo, _clinic_repo())

    with pytest.raises(AppointmentAlreadyDecidedError, match="Иванова Анна"):
        await service.complete_appointment_by_admin(already_decided, staff_telegram_id=999)


@pytest.mark.asyncio
async def test_resolve_decision_label_falls_back_when_user_id_is_none():
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(FakeAppointmentRepository(), FakeUserRepo(admin=admin), FakeStaffRepo(staff), _clinic_repo())

    label = await service.resolve_decision_label(None)

    assert label == "Другой сотрудник"


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
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

    with pytest.raises(SlotUnavailableError):
        await service.confirm_pending_request(1, staff_telegram_id=999)

    assert appt_repo.status_updates == []


@pytest.mark.asyncio
async def test_confirm_pending_request_succeeds_when_slot_free():
    own = _appt(1, 50, "2026-07-10 14:30", AppointmentStatus.PENDING, created_by=CreatedBy.CLIENT, client_id=7)
    appt_repo = FakeAppointmentRepository([own])
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

    appointment = await service.confirm_pending_request(1, staff_telegram_id=999)

    assert appointment.status is AppointmentStatus.CONFIRMED
    assert appt_repo.status_updates == [(1, AppointmentStatus.CONFIRMED)]


@pytest.mark.asyncio
async def test_propose_new_datetime_raises_when_proposed_slot_already_confirmed():
    proposed_datetime = _future_datetime(days=3, time_str="10:00")
    own = _appt(1, 50, "2026-07-10 14:30", AppointmentStatus.PENDING, created_by=CreatedBy.CLIENT, client_id=7)
    other = _appt(2, 50, proposed_datetime, AppointmentStatus.CONFIRMED, client_id=8)
    appt_repo = FakeAppointmentRepository([own, other])
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

    with pytest.raises(SlotUnavailableError):
        await service.propose_new_datetime(
            1, staff_telegram_id=999, proposed_datetime=proposed_datetime, kind="booking"
        )

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
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

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
    admin, staff = _admin_with_scope("clinic")
    service = AppointmentManagement(appt_repo, FakeUserRepo(_owning_client(), admin=admin), FakeStaffRepo(staff), _clinic_repo())

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


# --- MAX_BOOKINGS_PER_SLOT capacity (mm instances) ---
#
# zb instances leave MAX_BOOKINGS_PER_SLOT as None -- exercised by the tests
# above, where a single CONFIRMED row already blocks a slot. mm instances set
# it to 3, switching _ensure_slot_available/get_available_slots onto the
# CONFIRMED+PENDING counting branch instead. MAX_BOOKINGS_PER_SLOT is bound
# by name at import time inside appointment_management, so BOT_INSTANCE/env
# monkeypatching would not reach the already-imported name -- it must be
# monkeypatched directly on that module (mirrors how get_current_tashkent_datetime
# is patched at its call site elsewhere in this file).


@pytest.mark.asyncio
@pytest.mark.parametrize("statuses", [
    [],
    [AppointmentStatus.CONFIRMED],
    [AppointmentStatus.PENDING],
    [AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING],
])
async def test_ensure_slot_available_allows_below_max_bookings_per_slot(monkeypatch, statuses):
    monkeypatch.setattr("bot.services.appointment.appointment_management.MAX_BOOKINGS_PER_SLOT", 3)
    doctor_id = 50
    slot = "2026-07-20 10:30"
    appointments = [
        _appt(i + 1, doctor_id, slot, status, client_id=100 + i)
        for i, status in enumerate(statuses)
    ]
    appt_repo = FakeAppointmentRepository(appointments)
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    await service._ensure_slot_available(doctor_id, slot, None, 999)  # must not raise


@pytest.mark.asyncio
@pytest.mark.parametrize("statuses", [
    [AppointmentStatus.CONFIRMED, AppointmentStatus.CONFIRMED, AppointmentStatus.CONFIRMED],
    [AppointmentStatus.PENDING, AppointmentStatus.PENDING, AppointmentStatus.PENDING],
    [AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
])
async def test_ensure_slot_available_raises_when_max_bookings_per_slot_reached(monkeypatch, statuses):
    monkeypatch.setattr("bot.services.appointment.appointment_management.MAX_BOOKINGS_PER_SLOT", 3)
    doctor_id = 50
    slot = "2026-07-20 10:30"
    appointments = [
        _appt(i + 1, doctor_id, slot, status, client_id=100 + i)
        for i, status in enumerate(statuses)
    ]
    appt_repo = FakeAppointmentRepository(appointments)
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    with pytest.raises(SlotUnavailableError):
        await service._ensure_slot_available(doctor_id, slot, None, 999)


@pytest.mark.asyncio
async def test_ensure_slot_available_excludes_own_appointment_id_from_capacity_count(monkeypatch):
    """Rescheduling appointment 1 back onto its own current slot must not count
    itself among the 3 capacity slots -- only the other 2 existing rows should
    count, leaving room for the appointment being modified."""
    monkeypatch.setattr("bot.services.appointment.appointment_management.MAX_BOOKINGS_PER_SLOT", 3)
    doctor_id = 50
    slot = "2026-07-20 10:30"
    appointments = [
        _appt(1, doctor_id, slot, AppointmentStatus.CONFIRMED, client_id=7),
        _appt(2, doctor_id, slot, AppointmentStatus.PENDING, client_id=8),
        _appt(3, doctor_id, slot, AppointmentStatus.PENDING, client_id=9),
    ]
    appt_repo = FakeAppointmentRepository(appointments)
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    await service._ensure_slot_available(doctor_id, slot, exclude_appointment_id=1, client_id=999)  # must not raise


@pytest.mark.asyncio
async def test_ensure_slot_available_ignores_finalized_statuses_toward_capacity(monkeypatch):
    """CANCELLED/COMPLETED/NO_SHOW/EXPIRED rows never count toward capacity --
    stacking 4 of them on the same slot alongside only 2 CONFIRMED/PENDING rows
    must not push the count to the MAX_BOOKINGS_PER_SLOT=3 threshold. This also
    proves the fake repo's statuses filtering is real, not vacuous."""
    monkeypatch.setattr("bot.services.appointment.appointment_management.MAX_BOOKINGS_PER_SLOT", 3)
    doctor_id = 50
    slot = "2026-07-20 10:30"
    appointments = [
        _appt(1, doctor_id, slot, AppointmentStatus.CONFIRMED, client_id=7),
        _appt(2, doctor_id, slot, AppointmentStatus.PENDING, client_id=8),
        _appt(3, doctor_id, slot, AppointmentStatus.CANCELLED, client_id=9),
        _appt(4, doctor_id, slot, AppointmentStatus.COMPLETED, client_id=10),
        _appt(5, doctor_id, slot, AppointmentStatus.NO_SHOW, client_id=11),
        _appt(6, doctor_id, slot, AppointmentStatus.EXPIRED, client_id=12),
    ]
    appt_repo = FakeAppointmentRepository(appointments)
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    await service._ensure_slot_available(doctor_id, slot, None, 999)  # must not raise


@pytest.mark.asyncio
async def test_get_available_slots_keeps_slot_below_capacity_but_excludes_slot_at_max(monkeypatch):
    """A slot with 1 or 2 existing CONFIRMED/PENDING bookings must still be
    offered -- only the 3rd booking (reaching MAX_BOOKINGS_PER_SLOT=3) fills
    it and removes it from the returned list."""
    monkeypatch.setattr("bot.services.appointment.appointment_management.MAX_BOOKINGS_PER_SLOT", 3)
    doctor_id = 50
    day = date(2026, 7, 20)
    now = datetime(2026, 7, 1, 9, 0)

    appt_repo = FakeAppointmentRepository([
        _appt(1, doctor_id, "2026-07-20 10:00", AppointmentStatus.CONFIRMED, client_id=7),
        _appt(2, doctor_id, "2026-07-20 10:30", AppointmentStatus.CONFIRMED, client_id=8),
        _appt(3, doctor_id, "2026-07-20 10:30", AppointmentStatus.PENDING, client_id=9),
        _appt(4, doctor_id, "2026-07-20 11:00", AppointmentStatus.CONFIRMED, client_id=10),
        _appt(5, doctor_id, "2026-07-20 11:00", AppointmentStatus.PENDING, client_id=11),
        _appt(6, doctor_id, "2026-07-20 11:00", AppointmentStatus.PENDING, client_id=12),
    ])
    service = AppointmentManagement(appt_repo, FakeUserRepo(_client()), FakeStaffRepo(None), _clinic_repo())

    slots = await service.get_available_slots(doctor_id, day, now)

    assert "10:00" in slots  # 1 booking -- still available
    assert "10:30" in slots  # 2 bookings -- still available
    assert "11:00" not in slots  # 3 bookings -- at capacity, excluded


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


# resolve_notification_recipients: the treating doctor plus every clinic-scope
# admin of the appointment's clinic, deduplicated by telegram_user_id. Every
# admin/staff-facing notification call site (12 across appointment_jobs.py and
# the client handlers) now fans out through this single method instead of
# targeting a single admin telegram id alone.


class FakeRecipientUserRepo:
    def __init__(self, users_by_id=None, users_by_telegram_id=None):
        self.users_by_id = users_by_id or {}
        self.users_by_telegram_id = users_by_telegram_id or {}

    async def get_user_by_id(self, user_id):
        return self.users_by_id.get(user_id)

    async def get_user_by_telegram_id(self, telegram_user_id):
        return self.users_by_telegram_id.get(telegram_user_id)


def _recipient_appointment(doctor_id=None, clinic_id=1):
    return Appointment(
        clinic_id=clinic_id,
        client_id=7,
        doctor_id=doctor_id,
        datetime="2026-08-01 10:00",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        id=1,
    )


@pytest.mark.asyncio
async def test_resolve_notification_recipients_returns_doctor_only_when_no_clinic_scope_staff():
    doctor = User(full_name="Доктор", phone="+998900000001", role=Role.ADMIN, ID=42, telegram_user_id=555)
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeRecipientUserRepo(users_by_id={42: doctor}),
        FakeStaffRepo(None),
        _clinic_repo(),
    )

    recipients = await service.resolve_notification_recipients(_recipient_appointment(doctor_id=42))

    assert [r.telegram_user_id for r in recipients] == [555]


@pytest.mark.asyncio
async def test_resolve_notification_recipients_returns_clinic_scope_staff_when_no_doctor():
    admin = User(full_name="Админ", phone="+998900000002", role=Role.ADMIN, ID=10, telegram_user_id=999)
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeRecipientUserRepo(users_by_telegram_id={999: admin}),
        FakeStaffRepo({999: Staff(telegram_user_id=999, clinic_id=1, visibility_scope="clinic")}),
        _clinic_repo(),
    )

    recipients = await service.resolve_notification_recipients(_recipient_appointment(doctor_id=None))

    assert [r.telegram_user_id for r in recipients] == [999]


@pytest.mark.asyncio
async def test_resolve_notification_recipients_excludes_own_scope_and_unset_scope_staff():
    """Only visibility_scope == 'clinic' staff are fanned out to -- 'own'-scoped
    and unset-scope staff (which the rest of the codebase treats as own-only
    visibility) must not receive admin-facing notifications for someone else's
    appointment."""
    own_scope = User(full_name="Свой", phone="+998900000003", role=Role.ADMIN, ID=11, telegram_user_id=111)
    unset_scope = User(full_name="Без scope", phone="+998900000004", role=Role.ADMIN, ID=12, telegram_user_id=222)
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeRecipientUserRepo(users_by_telegram_id={111: own_scope, 222: unset_scope}),
        FakeStaffRepo({
            111: Staff(telegram_user_id=111, clinic_id=1, visibility_scope="own"),
            222: Staff(telegram_user_id=222, clinic_id=1, visibility_scope=None),
        }),
        _clinic_repo(),
    )

    recipients = await service.resolve_notification_recipients(_recipient_appointment(doctor_id=None))

    assert recipients == []


@pytest.mark.asyncio
async def test_resolve_notification_recipients_combines_doctor_and_distinct_clinic_staff():
    doctor = User(full_name="Доктор", phone="+998900000005", role=Role.ADMIN, ID=42, telegram_user_id=555)
    admin1 = User(full_name="Админ1", phone="+998900000006", role=Role.ADMIN, ID=10, telegram_user_id=999)
    admin2 = User(full_name="Админ2", phone="+998900000007", role=Role.ADMIN, ID=11, telegram_user_id=1000)
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeRecipientUserRepo(
            users_by_id={42: doctor},
            users_by_telegram_id={999: admin1, 1000: admin2},
        ),
        FakeStaffRepo({
            999: Staff(telegram_user_id=999, clinic_id=1, visibility_scope="clinic"),
            1000: Staff(telegram_user_id=1000, clinic_id=1, visibility_scope="clinic"),
        }),
        _clinic_repo(),
    )

    recipients = await service.resolve_notification_recipients(_recipient_appointment(doctor_id=42))

    assert {r.telegram_user_id for r in recipients} == {555, 999, 1000}


@pytest.mark.asyncio
async def test_resolve_notification_recipients_dedupes_doctor_who_is_also_clinic_scope_admin():
    """The treating doctor is ALSO a clinic-scope admin for the same clinic (a
    common real-world setup: a solo doctor who administers their own clinic-scope
    account) -- must resolve to exactly one recipient, not two duplicate sends."""
    doctor_and_admin = User(
        full_name="Доктор-Админ", phone="+998900000008", role=Role.ADMIN, ID=42, telegram_user_id=555,
    )
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeRecipientUserRepo(
            users_by_id={42: doctor_and_admin},
            users_by_telegram_id={555: doctor_and_admin},
        ),
        FakeStaffRepo({555: Staff(telegram_user_id=555, clinic_id=1, visibility_scope="clinic")}),
        _clinic_repo(),
    )

    recipients = await service.resolve_notification_recipients(_recipient_appointment(doctor_id=42))

    assert len(recipients) == 1
    assert recipients[0].telegram_user_id == 555


@pytest.mark.asyncio
async def test_resolve_notification_recipients_returns_empty_when_no_doctor_and_no_clinic_staff():
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeRecipientUserRepo(),
        FakeStaffRepo(None),
        _clinic_repo(),
    )

    recipients = await service.resolve_notification_recipients(_recipient_appointment(doctor_id=None))

    assert recipients == []


@pytest.mark.asyncio
async def test_resolve_notification_recipients_skips_doctor_id_that_does_not_resolve_to_a_user():
    """A stale/dangling doctor_id (e.g. the doctor account was deleted) must not
    crash resolution -- it's simply excluded, falling back to whatever
    clinic-scope staff exist."""
    service = AppointmentManagement(
        FakeAppointmentRepository(),
        FakeRecipientUserRepo(),
        FakeStaffRepo(None),
        _clinic_repo(),
    )

    recipients = await service.resolve_notification_recipients(_recipient_appointment(doctor_id=999))

    assert recipients == []


# --- Real-DB workflow tests: AppointmentManagement against a real SQLite DB ---
#
# Every test above in this file drives AppointmentManagement with
# FakeAppointmentRepository, an in-memory Python object with no real schema,
# indexes, or constraints underneath it. That is exactly the blind spot that
# hid the originally reported production bug: AppointmentRepository.init()
# unconditionally created a DB-level partial UNIQUE INDEX
# (idx_appointments_doctor_datetime_confirmed) on (admin_id, datetime) WHERE
# status = 'confirmed'. For mm instances (capacity 3, CONFIRMED+PENDING
# combined) this silently overrode the service-layer capacity logic the
# moment a 2nd/3rd booking at the same slot became CONFIRMED -- e.g. via the
# walk-in/no-telegram-account auto-confirm path in create_appointment -- and
# the user reported a 2nd mm booking failing with SlotUnavailableError even
# though _ensure_slot_available alone allows up to 3. A fake repository can
# never reproduce that: it has no unique index to violate.
#
# The tests below wire a REAL AppointmentRepository/UserRepository/
# StaffRepository/ClinicRepository onto a REAL in-memory SQLite connection --
# no fakes -- mirroring the _in_memory_repos() helper in
# tests/test_appointment_repository.py, and drive every scenario through the
# actual service methods (create_appointment / create_self_booking), never
# through raw repository inserts.

_real_seed_counter = itertools.count(1)


async def _real_service(instance: str, max_bookings_per_slot: int | None = None):
    """Wires a real AppointmentRepository/UserRepository/StaffRepository/
    ClinicRepository onto a fresh in-memory SQLite connection and returns
    (connection, service, user_repo, doctor_telegram_id, clinic_id).

    Mirrors production bot/run.py, which calls
    appointment_repo.init(MAX_BOOKINGS_PER_SLOT) exactly once (None for zb, 3
    for mm) -- so this helper does the same, never a no-arg init() followed
    by a second init(3) call, to keep the DB-index-vs-no-index branch exactly
    as it is in production for each instance."""
    connection = await aiosqlite.connect(":memory:")
    await connection.execute("PRAGMA foreign_keys = ON")

    clinic_repo = ClinicRepository(connection)
    user_repo = UserRepository(connection)
    staff_repo = StaffRepository(connection)
    appointment_repo = AppointmentRepository(connection)

    await clinic_repo.init(instance)
    await user_repo.init()
    await UserSettingsRepository(connection).init()
    await staff_repo.init(instance)
    await appointment_repo.init(max_bookings_per_slot)

    service = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)
    doctor_telegram_id = STAFF_SEED_BY_INSTANCE[instance][0]
    clinic = await clinic_repo.get_only_clinic()

    return connection, service, user_repo, doctor_telegram_id, clinic.clinic_id


async def _real_admin(user_repo: UserRepository, telegram_user_id: int) -> User:
    """Seeds a real admin/doctor User row for the already-seeded Staff row at
    telegram_user_id (STAFF_SEED_BY_INSTANCE) -- needed because
    create_appointment/create_self_booking look the acting doctor up as a
    User row (get_user_by_telegram_id/get_user_by_id), not just as Staff."""
    n = next(_real_seed_counter)
    await user_repo.create_user(
        User(full_name=f"Admin {n}", phone=f"+998900{n:06d}", role=Role.ADMIN, telegram_user_id=telegram_user_id)
    )
    return await user_repo.get_user_by_telegram_id(telegram_user_id)


async def _real_walk_in_client(user_repo: UserRepository) -> User:
    """A client with no linked Telegram account. create_appointment always
    auto-confirms these (the walk-in/no-telegram-account path) regardless of
    lead time -- this is the exact path that triggered the originally
    reported production bug when a 2nd/3rd such booking hit the same slot."""
    n = next(_real_seed_counter)
    phone = f"+998901{n:06d}"
    await user_repo.create_user(User(full_name=f"Walk-in {n}", phone=phone, role=Role.CLIENT))
    return await user_repo.get_client_by_phone(phone)


async def _real_self_booking_client(user_repo: UserRepository, clinic_id: int) -> User:
    n = next(_real_seed_counter)
    telegram_user_id = 800_000_000 + n
    await user_repo.create_user(
        User(
            full_name=f"Client {n}", phone=f"+998902{n:06d}", role=Role.CLIENT,
            telegram_user_id=telegram_user_id, clinic_id=clinic_id,
        )
    )
    return await user_repo.get_user_by_telegram_id(telegram_user_id)


async def _real_book_confirmed(service, user_repo, doctor_telegram_id, slot):
    """Books a CONFIRMED appointment via create_appointment's walk-in
    auto-confirm path (a fresh client with telegram_user_id=None)."""
    client = await _real_walk_in_client(user_repo)
    appointment = await service.create_appointment(
        doctor_telegram_id,
        {"phone": client.phone, "appointment_datetime": slot, "purpose": "Консультация"},
    )
    assert appointment.status is AppointmentStatus.CONFIRMED
    return client, appointment


async def _real_book_pending(service, user_repo, admin_id, clinic_id, slot):
    """Books a PENDING appointment via a normal client self-booking (a fresh
    client with a linked Telegram account)."""
    client = await _real_self_booking_client(user_repo, clinic_id)
    appointment = await service.create_self_booking(
        client.telegram_user_id,
        {"staff_user_id": admin_id, "appointment_datetime": slot, "complaint": "Болит зуб"},
    )
    assert appointment.status is AppointmentStatus.PENDING
    return client, appointment


@pytest.mark.asyncio
async def test_mm_slot_allows_three_confirmed_walk_ins_and_blocks_a_fourth(monkeypatch):
    """Regression repro for the originally reported production bug: on an mm
    instance (capacity 3), 3 different clients getting a CONFIRMED
    appointment at the identical doctor+datetime slot must all succeed, and
    only a 4th booking at that slot must be rejected. Each of the 3 goes
    through create_appointment's walk-in/no-telegram-account auto-confirm
    path (client.telegram_user_id is None), which is exactly the path that
    hit the stray idx_appointments_doctor_datetime_confirmed unique index in
    production and raised SlotUnavailableError on the 2nd booking, even
    though the service-layer capacity logic alone allows up to 3."""
    monkeypatch.setattr("bot.services.appointment.appointment_management.MAX_BOOKINGS_PER_SLOT", 3)
    connection, service, user_repo, doctor_telegram_id, clinic_id = await _real_service("mm", max_bookings_per_slot=3)
    try:
        await _real_admin(user_repo, doctor_telegram_id)
        slot = _future_datetime(days=10)

        for _ in range(3):
            await _real_book_confirmed(service, user_repo, doctor_telegram_id, slot)

        fourth_client = await _real_walk_in_client(user_repo)
        with pytest.raises(SlotUnavailableError) as exc_info:
            await service.create_appointment(
                doctor_telegram_id,
                {"phone": fourth_client.phone, "appointment_datetime": slot, "purpose": "Консультация"},
            )

        assert str(exc_info.value) == SLOT_UNAVAILABLE_MESSAGE
    finally:
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statuses",
    [
        (AppointmentStatus.CONFIRMED, AppointmentStatus.CONFIRMED, AppointmentStatus.CONFIRMED),
        (AppointmentStatus.PENDING, AppointmentStatus.PENDING, AppointmentStatus.PENDING),
        (AppointmentStatus.CONFIRMED, AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING),
        (AppointmentStatus.CONFIRMED, AppointmentStatus.PENDING, AppointmentStatus.PENDING),
    ],
    ids=["all-confirmed", "all-pending", "2-confirmed-1-pending", "1-confirmed-2-pending"],
)
async def test_mm_slot_allows_exactly_three_active_bookings_for_every_status_combo_and_blocks_a_fourth(
    monkeypatch, statuses,
):
    """All 4 status compositions that sum to the mm capacity of 3 (CONFIRMED
    and PENDING combined): 3 distinct clients must always succeed, and a 4th
    booking of either status at the same slot must always be rejected once
    capacity is reached."""
    monkeypatch.setattr("bot.services.appointment.appointment_management.MAX_BOOKINGS_PER_SLOT", 3)
    connection, service, user_repo, doctor_telegram_id, clinic_id = await _real_service("mm", max_bookings_per_slot=3)
    try:
        admin = await _real_admin(user_repo, doctor_telegram_id)
        slot = _future_datetime(days=11)

        for status in statuses:
            if status is AppointmentStatus.CONFIRMED:
                await _real_book_confirmed(service, user_repo, doctor_telegram_id, slot)
            else:
                await _real_book_pending(service, user_repo, admin.ID, clinic_id, slot)

        with pytest.raises(SlotUnavailableError) as confirmed_exc:
            await _real_book_confirmed(service, user_repo, doctor_telegram_id, slot)
        assert str(confirmed_exc.value) == SLOT_UNAVAILABLE_MESSAGE

        with pytest.raises(SlotUnavailableError) as pending_exc:
            await _real_book_pending(service, user_repo, admin.ID, clinic_id, slot)
        assert str(pending_exc.value) == SLOT_UNAVAILABLE_MESSAGE
    finally:
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "instance,max_bookings_per_slot",
    [("zb", None), ("mm", 3)],
)
async def test_create_self_booking_raises_duplicate_message_when_same_client_rebooks_own_pending_slot(
    monkeypatch, instance, max_bookings_per_slot,
):
    """A client's own duplicate PENDING request at the same doctor+slot must
    always be blocked in both instances -- in zb this is a NEW protection:
    zb's raw capacity check alone only blocks a slot once a row is CONFIRMED
    (a different client's PENDING never blocked zb before, and still
    doesn't -- see test_zb_slot_allows_second_pending_from_different_client
    below), but the SAME client's own PENDING duplicate must now be rejected
    regardless of instance."""
    if max_bookings_per_slot is not None:
        monkeypatch.setattr(
            "bot.services.appointment.appointment_management.MAX_BOOKINGS_PER_SLOT", max_bookings_per_slot
        )
    # MAX_PENDING_REQUESTS_PER_CLIENT is bound by name at import time inside
    # appointment_management (same as MAX_BOOKINGS_PER_SLOT), and its real
    # (zb) value is 1. This test needs a 2nd create_self_booking call by the
    # same client to actually reach _ensure_slot_available's duplicate check
    # instead of being turned away earlier by the unrelated pending-request-
    # limit guard, so it's raised here for both instances.
    monkeypatch.setattr("bot.services.appointment.appointment_management.MAX_PENDING_REQUESTS_PER_CLIENT", 10)

    connection, service, user_repo, doctor_telegram_id, clinic_id = await _real_service(instance, max_bookings_per_slot)
    try:
        admin = await _real_admin(user_repo, doctor_telegram_id)
        client = await _real_self_booking_client(user_repo, clinic_id)
        slot = _future_datetime(days=15)

        first = await service.create_self_booking(
            client.telegram_user_id,
            {"staff_user_id": admin.ID, "appointment_datetime": slot, "complaint": "Болит зуб"},
        )
        assert first.status is AppointmentStatus.PENDING

        with pytest.raises(SlotUnavailableError) as exc_info:
            await service.create_self_booking(
                client.telegram_user_id,
                {"staff_user_id": admin.ID, "appointment_datetime": slot, "complaint": "Болит зуб"},
            )

        assert str(exc_info.value) == DUPLICATE_CLIENT_SLOT_MESSAGE
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_create_appointment_raises_duplicate_message_when_admin_rebooks_same_client_and_slot():
    """Admin-booking direction of the same-client duplicate protection: a 2nd
    create_appointment call for the same client+doctor+slot, while the first
    is still active, must be rejected with the duplicate-slot message -- not
    silently create a 2nd row for the same client at the same time."""
    connection, service, user_repo, doctor_telegram_id, clinic_id = await _real_service("zb")
    try:
        await _real_admin(user_repo, doctor_telegram_id)
        client = await _real_walk_in_client(user_repo)
        slot = _future_datetime(days=16)

        first = await service.create_appointment(
            doctor_telegram_id,
            {"phone": client.phone, "appointment_datetime": slot, "purpose": "Консультация"},
        )
        assert first.status is AppointmentStatus.CONFIRMED

        with pytest.raises(SlotUnavailableError) as exc_info:
            await service.create_appointment(
                doctor_telegram_id,
                {"phone": client.phone, "appointment_datetime": slot, "purpose": "Консультация"},
            )

        assert str(exc_info.value) == DUPLICATE_CLIENT_SLOT_MESSAGE
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_zb_slot_blocks_second_confirmed_from_different_client():
    """zb regression guard: default mode (no MAX_BOOKINGS_PER_SLOT
    monkeypatch, appointment_repo.init() with no args, matching production
    zb). A 2nd CONFIRMED booking from a DIFFERENT client at the same slot
    must still be rejected with the plain slot-unavailable message, not the
    duplicate-client one."""
    connection, service, user_repo, doctor_telegram_id, clinic_id = await _real_service("zb")
    try:
        await _real_admin(user_repo, doctor_telegram_id)
        slot = _future_datetime(days=13)

        await _real_book_confirmed(service, user_repo, doctor_telegram_id, slot)

        second_client = await _real_walk_in_client(user_repo)
        with pytest.raises(SlotUnavailableError) as exc_info:
            await service.create_appointment(
                doctor_telegram_id,
                {"phone": second_client.phone, "appointment_datetime": slot, "purpose": "Консультация"},
            )

        assert str(exc_info.value) == SLOT_UNAVAILABLE_MESSAGE
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_zb_slot_allows_second_pending_from_different_client():
    """zb regression guard: zb's original design -- a PENDING booking never
    blocks a DIFFERENT client from also going PENDING on the same slot; only
    a CONFIRMED row blocks others. This must survive unchanged after the
    same-client duplicate-check addition in _ensure_slot_available."""
    connection, service, user_repo, doctor_telegram_id, clinic_id = await _real_service("zb")
    try:
        admin = await _real_admin(user_repo, doctor_telegram_id)
        slot = _future_datetime(days=14)

        await _real_book_pending(service, user_repo, admin.ID, clinic_id, slot)
        _, second = await _real_book_pending(service, user_repo, admin.ID, clinic_id, slot)

        assert second.status is AppointmentStatus.PENDING
    finally:
        await connection.close()


