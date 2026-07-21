"""Global end-to-end tests exercising the real
Handler-equivalent -> Service -> Repository -> DB flow against a real
SQLite database (file-backed via tmp_path, single shared connection per
test, no repository mocks, no `:memory:`).

Every scenario is driven through the same public services a handler would
call (RegistrationService, ClientManagement, ClientPaginationService,
AppointmentManagement, AppointmentPaginationService, AppointmentScheduler,
AppointmentNotificationService), never through repositories directly for
state-changing actions. Final state is always re-read through repository
`get_*` methods.

Scope (see docs/e2e_test_prompt.md):
1. Client registration (idempotent by phone).
2. Admin client management (create/search/edit/name-change approval/
   rejection/delete + pagination visibility).
3. Appointment lifecycle (admin-created + self-booking, confirm/reject,
   reschedule from both sides, cancellation, completion, pagination by tab).
4. Notifications & scheduling (reminder/completion job registration and
   delivery effects, job cancellation on appointment cancellation).
"""

from datetime import timedelta
from types import SimpleNamespace

import aiosqlite
import pytest
import pytest_asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.exceptions.appointment_exceptions import PendingRequestLimitExceededError
from bot.exceptions.user_exceptions import UserAlreadyExistsError
from bot.models.user import User
from bot.repositories.appointment_repository import AppointmentRepository
from bot.repositories.client_clinic_repository import ClientClinicRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.staff_repository import StaffRepository
from bot.repositories.user_repository import UserRepository
from bot.services.appointment.appointment_jobs import complete_appointment
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.appointment_notifications import AppointmentNotificationService
from bot.services.appointment.appointment_pagination_service import AppointmentPaginationService
from bot.services.appointment.appointment_scheduler import AppointmentScheduler
from bot.services.client.client_management import ClientManagement
from bot.services.client.client_pagination_service import ClientPaginationService
from bot.services.utils.date_parser import get_current_tashkent_datetime
from bot.services.utils.registration import RegistrationService
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.role import Role

CLINIC_TOKEN = "x7A92JdPkLmQe81"
ADMIN_TELEGRAM_ID = 685889801  # one of the 3 fixed staff rows seeded by StaffRepository.init()


class FakeBot:
    """Captures outbound Telegram calls instead of hitting the real Bot API."""

    def __init__(self):
        self.sent_messages: list[SimpleNamespace] = []
        self.edited_messages: list[SimpleNamespace] = []
        self._next_message_id = 1

    async def send_message(self, chat_id, text, **kwargs):
        message = SimpleNamespace(message_id=self._next_message_id, chat_id=chat_id, text=text)
        self._next_message_id += 1
        self.sent_messages.append(message)
        return message

    async def edit_message_text(self, chat_id, message_id, text, **kwargs):
        self.edited_messages.append(SimpleNamespace(chat_id=chat_id, message_id=message_id, text=text))


def _future_datetime(days: int = 3, hours: int = 0) -> str:
    dt = get_current_tashkent_datetime() + timedelta(days=days, hours=hours)
    return dt.strftime("%Y-%m-%d %H:%M")


@pytest_asyncio.fixture
async def e2e(tmp_path):
    connection = await aiosqlite.connect(tmp_path / "test.db")
    await connection.execute("PRAGMA foreign_keys = ON")

    clinic_repo = ClinicRepository(connection)
    user_repo = UserRepository(connection)
    staff_repo = StaffRepository(connection)
    appointment_repo = AppointmentRepository(connection)
    client_clinic_repo = ClientClinicRepository(connection)

    await clinic_repo.init()
    await user_repo.init()
    await staff_repo.init()
    await appointment_repo.init()
    await client_clinic_repo.init()

    await user_repo.create_user(
        User(
            full_name="Каримов Аскар Тимурович",
            phone="+998901112233",
            role=Role.ADMIN,
            clinic_id=1,
            telegram_user_id=ADMIN_TELEGRAM_ID,
        )
    )
    admin = await user_repo.get_user_by_telegram_id(ADMIN_TELEGRAM_ID)

    fake_bot = FakeBot()
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")

    client_management = ClientManagement(
        user_repo, staff_repo, clinic_repo, client_clinic_repository=client_clinic_repo,
    )
    notification_service = AppointmentNotificationService(fake_bot, user_repo, appointment_repo)
    appointment_management = AppointmentManagement(
        appointment_repo, user_repo, staff_repo, clinic_repo, client_management=client_management,
    )

    env = SimpleNamespace(
        connection=connection,
        clinic_repo=clinic_repo,
        user_repo=user_repo,
        staff_repo=staff_repo,
        appointment_repo=appointment_repo,
        admin=admin,
        fake_bot=fake_bot,
        scheduler=scheduler,
        registration_service=RegistrationService(user_repo, clinic_repo),
        client_management=client_management,
        client_pagination=ClientPaginationService(user_repo),
        appointment_management=appointment_management,
        appointment_pagination=AppointmentPaginationService(appointment_repo),
        notification_service=notification_service,
        appointment_scheduler=AppointmentScheduler(
            scheduler, notification_service, appointment_management,
        ),
    )

    yield env

    if scheduler.running:
        scheduler.shutdown(wait=False)
    await connection.close()


async def _create_client(e2e, full_name: str, phone: str) -> User:
    """Arrange helper: create an unclaimed client via the service under test
    and re-read it back through the repository to obtain its assigned ID
    (ClientManagement.create_client does not return the ID)."""
    await e2e.client_management.create_client(ADMIN_TELEGRAM_ID, {"full_name": full_name, "phone": phone})
    return await e2e.user_repo.get_client_by_phone(phone)


async def _create_registered_client(e2e, full_name: str, phone: str, telegram_user_id: int) -> User:
    """Arrange helper: a client already bound to a telegram account, used by
    scenarios (appointments/notifications) that are not themselves testing
    registration."""
    await e2e.user_repo.create_user(
        User(full_name=full_name, phone=phone, role=Role.CLIENT, clinic_id=1, telegram_user_id=telegram_user_id)
    )
    return await e2e.user_repo.get_user_by_telegram_id(telegram_user_id)


# --------------------------------------------------------------------------
# 1. Client registration
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_registration_new_phone_then_idempotent_restart(e2e):
    clinic = await e2e.registration_service.get_clinic_by_token(CLINIC_TOKEN)
    assert clinic is not None
    assert clinic.clinic_id == 1
    assert clinic.name == "Зуб Мудрости"

    telegram_id = 555000111
    phone = "+998911234567"
    full_name = "Расулов Тимур Бахтиёрович"

    lookup = await e2e.registration_service.check_phone(phone, telegram_id)
    assert lookup.status == "not_found"

    user = await e2e.registration_service.register(
        telegram_user_id=telegram_id,
        full_name=full_name,
        phone=phone,
        role=Role.CLIENT,
        clinic_id=clinic.clinic_id,
    )
    assert user.telegram_user_id == telegram_id

    stored = await e2e.user_repo.get_user_by_telegram_id(telegram_id)
    assert stored.ID is not None
    assert stored.full_name == full_name
    assert stored.role is Role.CLIENT
    assert stored.clinic_id == clinic.clinic_id

    # Repeat /start with the same, already-registered telegram id: must not
    # create a duplicate row (idempotency), it must be rejected instead.
    with pytest.raises(UserAlreadyExistsError):
        await e2e.registration_service.check_phone(phone, telegram_id)

    assert await e2e.user_repo.count_all_clients() == 1


@pytest.mark.asyncio
async def test_client_registration_binds_to_existing_unclaimed_patient_by_phone(e2e):
    phone = "+998911234321"
    stored_name = "Юсупова Дилноза Акмаловна"

    unclaimed = await _create_client(e2e, stored_name, phone)
    assert unclaimed.telegram_user_id is None

    telegram_id = 555000222
    lookup = await e2e.registration_service.check_phone(phone, telegram_id, contact_user_id=telegram_id)
    assert lookup.status == "found_unclaimed"
    assert lookup.existing_user.ID == unclaimed.ID

    bound_user = await e2e.registration_service.register(
        telegram_user_id=telegram_id,
        full_name=stored_name,
        phone=phone,
        role=Role.CLIENT,
        clinic_id=1,
        existing_user_id=unclaimed.ID,
    )
    assert bound_user.ID == unclaimed.ID
    assert bound_user.telegram_user_id == telegram_id

    stored = await e2e.user_repo.get_client_by_phone(phone)
    assert stored.telegram_user_id == telegram_id
    assert await e2e.user_repo.count_all_clients() == 1


@pytest.mark.asyncio
async def test_self_registered_client_appears_in_clinic_scoped_search(e2e):
    client_clinic_repo = ClientClinicRepository(e2e.connection)
    await client_clinic_repo.init()
    registration_service = RegistrationService(
        e2e.user_repo, e2e.clinic_repo, client_clinic_repository=client_clinic_repo,
    )

    telegram_id = 555000333
    phone = "+998911119999"
    full_name = "Ахмедов Шерзод Даврон угли"

    registered = await registration_service.register(
        telegram_user_id=telegram_id,
        full_name=full_name,
        phone=phone,
        role=Role.CLIENT,
        clinic_id=1,
    )

    name_matches = await e2e.user_repo.get_clients_by_name_in_clinic(full_name, 1)
    assert [match.ID for match in name_matches] == [registered.ID]

    exact_matches = await e2e.user_repo.get_clients_by_exact_name(full_name, 1)
    assert [match.ID for match in exact_matches] == [registered.ID]

    phone_match = await e2e.user_repo.get_client_by_phone_in_clinic(phone, 1)
    assert phone_match.ID == registered.ID


# --------------------------------------------------------------------------
# 2. Admin client management
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_client_management_full_lifecycle(e2e):
    phone = "+998933214455"
    original_name = "Ахмедов Шерзод Баходирович"

    client = await _create_client(e2e, original_name, phone)
    assert client.ID is not None

    # Search: by phone and by (partial) full name.
    by_phone = await e2e.client_management.search_client({"phone": phone}, e2e.admin.clinic_id)
    assert [u.ID for u in by_phone] == [client.ID]

    by_name = await e2e.client_management.search_client({"full_name": "Ахмедов"}, e2e.admin.clinic_id)
    assert client.ID in {u.ID for u in by_name}

    # Visible in the client browser's paginated listing.
    listed = await e2e.client_pagination.paginate_clients("list", page=1, clinic_id=e2e.admin.clinic_id)
    assert client.ID in {u.ID for u in listed.items}

    # Edit: phone.
    new_phone = "+998933214499"
    updated = await e2e.client_management.update_client_phone(client.ID, new_phone, e2e.admin.clinic_id)
    assert updated.phone == new_phone

    # Edit: name-change request approved by the admin.
    requested_name = "Ахмедов Шерзод Тохирович"
    pending_user = await e2e.client_management.request_name_change(client.ID, requested_name)
    assert pending_user.pending_full_name == requested_name

    approved_user = await e2e.client_management.approve_name_change(client.ID, e2e.admin.clinic_id)
    assert approved_user.full_name == requested_name
    assert approved_user.pending_full_name is None

    persisted_after_approval = await e2e.client_management.get_client_by_id(client.ID, e2e.admin.clinic_id)
    assert persisted_after_approval.full_name == requested_name

    # Edit: a second name-change request, this time rejected by the admin.
    rejected_name = "Ахмедов Отабек Шерзодович"
    await e2e.client_management.request_name_change(client.ID, rejected_name)
    rejected_user = await e2e.client_management.reject_name_change(client.ID, e2e.admin.clinic_id)
    assert rejected_user.full_name == requested_name  # unchanged
    assert rejected_user.pending_full_name is None

    persisted_after_rejection = await e2e.client_management.get_client_by_id(client.ID, e2e.admin.clinic_id)
    assert persisted_after_rejection.full_name == requested_name

    # Delete: client disappears from lookups and from the browser listing.
    assert await e2e.client_management.delete_client(client.ID, e2e.admin.clinic_id) is True
    assert await e2e.client_management.get_client_by_id(client.ID, e2e.admin.clinic_id) is None

    listed_after_delete = await e2e.client_pagination.paginate_clients("list", page=1, clinic_id=e2e.admin.clinic_id)
    assert client.ID not in {u.ID for u in listed_after_delete.items}


# --------------------------------------------------------------------------
# 3. Appointment lifecycle
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_appointment_lifecycle_admin_created_confirm_reschedule_cancel(e2e):
    """Admin creates an appointment, client confirms it, then both sides
    negotiate a reschedule, and it is finally cancelled by the client."""
    client = await _create_registered_client(e2e, "Норов Азизбек Улугбекович", "+998977001122", 700000111)

    appointment = await e2e.appointment_management.create_appointment(
        ADMIN_TELEGRAM_ID,
        {"phone": client.phone, "appointment_datetime": _future_datetime(days=3), "purpose": "Консультация"},
    )
    assert appointment.status is AppointmentStatus.PENDING
    assert appointment.client_id == client.ID

    # Client confirms the admin-initiated appointment.
    confirmed = await e2e.appointment_management.confirm_appointment_by_client(
        appointment.id, client.telegram_user_id
    )
    assert confirmed.status is AppointmentStatus.CONFIRMED

    # Admin proposes a different time; client accepts it.
    proposed_time = _future_datetime(days=5)
    proposed = await e2e.appointment_management.propose_new_datetime(
        appointment.id, ADMIN_TELEGRAM_ID, proposed_time, kind="reschedule"
    )
    assert proposed.proposed_datetime == proposed_time

    accepted = await e2e.appointment_management.accept_proposed_datetime(appointment.id, client.telegram_user_id)
    assert accepted.datetime == proposed_time
    assert accepted.status is AppointmentStatus.CONFIRMED
    assert accepted.proposed_datetime is None

    # Client, in turn, requests a further reschedule; admin accepts it.
    client_proposed_time = _future_datetime(days=6)
    client_proposal = await e2e.appointment_management.request_reschedule_by_client(
        appointment.id, client.telegram_user_id, client_proposed_time
    )
    assert client_proposal.proposed_datetime == client_proposed_time

    reschedule_accepted = await e2e.appointment_management.accept_client_reschedule(
        appointment.id, ADMIN_TELEGRAM_ID
    )
    assert reschedule_accepted.datetime == client_proposed_time
    assert reschedule_accepted.proposed_datetime is None

    # Cancellation by the client, well outside the 1h cutoff window.
    cancelled = await e2e.appointment_management.cancel_appointment_by_client(appointment.id, client.telegram_user_id)
    assert cancelled.status is AppointmentStatus.CANCELLED

    stored = await e2e.appointment_repo.get_appointment_by_id(appointment.id)
    assert stored.status is AppointmentStatus.CANCELLED
    assert stored.datetime == client_proposed_time


@pytest.mark.asyncio
async def test_appointment_lifecycle_self_booking_confirm_and_reject(e2e):
    """A client books directly; the clinic accepts one request and declines
    another (the pending-request limit forces sequential requests)."""
    client_a = await _create_registered_client(e2e, "Тошева Мадина Рустамовна", "+998977002233", 700000222)
    client_b = await _create_registered_client(e2e, "Юлдашев Комрон Фарходович", "+998977003344", 700000333)

    booking_a = await e2e.appointment_management.create_self_booking(
        client_a.telegram_user_id,
        {"staff_user_id": e2e.admin.ID, "appointment_datetime": _future_datetime(days=2), "complaint": "Боль в зубе"},
    )
    assert booking_a.status is AppointmentStatus.PENDING
    assert booking_a.created_by.value == "client"

    # While booking_a is still PENDING, a second self-booking from the same
    # client must be rejected (MAX_PENDING_REQUESTS_PER_CLIENT = 1).
    with pytest.raises(PendingRequestLimitExceededError):
        await e2e.appointment_management.create_self_booking(
            client_a.telegram_user_id,
            {"staff_user_id": e2e.admin.ID, "appointment_datetime": _future_datetime(days=4), "complaint": "Осмотр"},
        )

    confirmed = await e2e.appointment_management.confirm_pending_request(booking_a.id, ADMIN_TELEGRAM_ID)
    assert confirmed.status is AppointmentStatus.CONFIRMED

    booking_b = await e2e.appointment_management.create_self_booking(
        client_b.telegram_user_id,
        {"staff_user_id": e2e.admin.ID, "appointment_datetime": _future_datetime(days=2, hours=1), "complaint": "Чистка"},
    )
    assert booking_b.status is AppointmentStatus.PENDING

    rejected = await e2e.appointment_management.reject_pending_request(booking_b.id, ADMIN_TELEGRAM_ID)
    assert rejected.status is AppointmentStatus.CANCELLED

    stored_a = await e2e.appointment_repo.get_appointment_by_id(booking_a.id)
    stored_b = await e2e.appointment_repo.get_appointment_by_id(booking_b.id)
    assert stored_a.status is AppointmentStatus.CONFIRMED
    assert stored_b.status is AppointmentStatus.CANCELLED


@pytest.mark.asyncio
async def test_appointment_lifecycle_self_booking_pending_direct_edit_then_confirm(e2e):
    """A client edits the datetime of their own still-PENDING self-booking request
    directly (same row, no proposal negotiation), then the clinic confirms it at
    the new time -- the row's id never changes across the edit."""
    client = await _create_registered_client(e2e, "Носирова Дилноза Акмаловна", "+998977005566", 700000555)

    booking = await e2e.appointment_management.create_self_booking(
        client.telegram_user_id,
        {"staff_user_id": e2e.admin.ID, "appointment_datetime": _future_datetime(days=2), "complaint": "Боль в зубе"},
    )
    assert booking.status is AppointmentStatus.PENDING

    new_datetime = _future_datetime(days=5)
    edited = await e2e.appointment_management.request_reschedule_by_client(
        booking.id, client.telegram_user_id, new_datetime,
    )

    assert edited.id == booking.id
    assert edited.datetime == new_datetime
    assert edited.status is AppointmentStatus.PENDING
    assert edited.proposed_datetime is None

    stored = await e2e.appointment_repo.get_appointment_by_id(booking.id)
    assert stored.datetime == new_datetime
    assert stored.status is AppointmentStatus.PENDING

    confirmed = await e2e.appointment_management.confirm_pending_request(booking.id, ADMIN_TELEGRAM_ID)
    assert confirmed.id == booking.id
    assert confirmed.status is AppointmentStatus.CONFIRMED
    assert confirmed.datetime == new_datetime


@pytest.mark.asyncio
async def test_appointment_completion_follow_up_and_pagination_by_tab(e2e):
    """Completion only asks the admin (does not auto-finalize); the admin's
    explicit answer is what finalizes COMPLETED. Also verifies that admin
    pagination by status tab reflects appointments as they change state."""
    client = await _create_registered_client(e2e, "Эргашев Botir Davronovich", "+998977004455", 700000444)

    pending_appt = await e2e.appointment_management.create_appointment(
        ADMIN_TELEGRAM_ID,
        {"phone": client.phone, "appointment_datetime": _future_datetime(days=2), "purpose": "Осмотр"},
    )
    confirmed_appt = await e2e.appointment_management.create_appointment(
        ADMIN_TELEGRAM_ID,
        {"phone": client.phone, "appointment_datetime": _future_datetime(days=3), "purpose": "Пломбирование"},
    )
    await e2e.appointment_management.confirm_appointment_by_client(confirmed_appt.id, client.telegram_user_id)

    # Pagination reflects the just-created rows in the correct tabs.
    pending_page = await e2e.appointment_pagination.paginate_all_appointments_by_tab("pending", page=1, clinic_id=1)
    confirmed_page = await e2e.appointment_pagination.paginate_all_appointments_by_tab("confirmed", page=1, clinic_id=1)
    assert pending_appt.id in {a.id for a in pending_page.items}
    assert confirmed_appt.id in {a.id for a in confirmed_page.items}
    assert confirmed_appt.id not in {a.id for a in pending_page.items}

    # The 1h follow-up fires: it must only prompt the admin, never touch status.
    await complete_appointment(e2e.appointment_management, e2e.notification_service, confirmed_appt.id)

    untouched = await e2e.appointment_repo.get_appointment_by_id(confirmed_appt.id)
    assert untouched.status is AppointmentStatus.CONFIRMED
    assert any(m.chat_id == ADMIN_TELEGRAM_ID for m in e2e.fake_bot.sent_messages)

    # The admin answers "Нет" (skip corrections): only this finalizes COMPLETED.
    finalized = await e2e.appointment_management.update_status(untouched, AppointmentStatus.COMPLETED)
    assert finalized.status is AppointmentStatus.COMPLETED

    completed_page = await e2e.appointment_pagination.paginate_all_appointments_by_tab("completed", page=1, clinic_id=1)
    confirmed_page_after = await e2e.appointment_pagination.paginate_all_appointments_by_tab("confirmed", page=1, clinic_id=1)
    assert confirmed_appt.id in {a.id for a in completed_page.items}
    assert confirmed_appt.id not in {a.id for a in confirmed_page_after.items}


# --------------------------------------------------------------------------
# 4. Notifications & reminders
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reminder_and_completion_jobs_scheduled_delivered_and_cancelled(e2e):
    client = await _create_registered_client(e2e, "Собирова Нилуфар Ахадовна", "+998977005566", 700000555)
    e2e.scheduler.start()

    booking = await e2e.appointment_management.create_self_booking(
        client.telegram_user_id,
        {"staff_user_id": e2e.admin.ID, "appointment_datetime": _future_datetime(days=3), "complaint": "Боль в десне"},
    )

    await e2e.appointment_scheduler.schedule_appointment_reminders(booking)
    await e2e.appointment_scheduler.schedule_appointment_completion(booking)
    await e2e.appointment_scheduler.schedule_pending_expiry(booking)

    job_ids = {job.id for job in e2e.scheduler.get_jobs()}
    assert job_ids == {
        f"appt_{booking.id}_24h",
        f"appt_{booking.id}_2h",
        f"appt_{booking.id}_complete",
        f"appt_{booking.id}_expire",
    }

    # Trigger the reminder/admin-notification delivery effects directly
    # (the same calls the real reminder job makes), without waiting on the
    # scheduler's real clock.
    sent_to_client = await e2e.notification_service.notify_client_reminder_with_buttons(booking)
    assert sent_to_client is True
    await e2e.notification_service.notify_admin_upcoming_appointment(
        ADMIN_TELEGRAM_ID, booking, client.full_name
    )

    assert any(m.chat_id == client.telegram_user_id for m in e2e.fake_bot.sent_messages)
    assert any(m.chat_id == ADMIN_TELEGRAM_ID for m in e2e.fake_bot.sent_messages)

    # Trigger the 1h completion follow-up delivery effect as well.
    await complete_appointment(e2e.appointment_management, e2e.notification_service, booking.id)
    completion_messages = [m for m in e2e.fake_bot.sent_messages if m.chat_id == ADMIN_TELEGRAM_ID]
    assert len(completion_messages) == 2  # upcoming-appointment reminder + completion follow-up

    # Clinic rejects the request: cancelling it must cancel every scheduled job.
    rejected = await e2e.appointment_management.reject_pending_request(booking.id, ADMIN_TELEGRAM_ID)
    assert rejected.status is AppointmentStatus.CANCELLED

    await e2e.appointment_scheduler.cancel_appointment_reminders(booking.id)
    await e2e.appointment_scheduler.cancel_appointment_completions(booking.id)
    await e2e.appointment_scheduler.cancel_pending_expiry(booking.id)

    assert e2e.scheduler.get_jobs() == []
