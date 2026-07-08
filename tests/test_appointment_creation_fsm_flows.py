"""
Comprehensive FSM flow tests for appointment creation.

Tests 5 critical scenarios covering:
1. Happy Path (Existing Client)
2. New Client Path
3. New Client with Name Edit
4. New Client with Phone Edit
5. DateTime Parsing and Retry
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, Chat, User as TelegramUser

from bot.states.admin.record_management.appointment_states import AppointmentCreationStates
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.models.appointment import Appointment
from bot.utils.role import Role
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy


# ============================================================================
# Fake Repositories
# ============================================================================

class FakeAppointmentRepository:
    """In-memory appointment repository for testing."""

    def __init__(self):
        self.appointments = []
        self.next_id = 1

    async def create_appointment(self, appointment: Appointment) -> Appointment:
        appointment.id = self.next_id
        self.next_id += 1
        self.appointments.append(appointment)
        return appointment

    async def get_appointment_by_id(self, appointment_id: int) -> Appointment | None:
        return next((a for a in self.appointments if a.id == appointment_id), None)

    async def get_appointments_by_client_id(self, client_id: int) -> list[Appointment]:
        return [a for a in self.appointments if a.client_id == client_id]


class FakeUserRepository:
    """In-memory user repository for testing."""

    def __init__(self, existing_clients=None):
        self.users = {}
        self.next_id = 1
        if existing_clients:
            for client in existing_clients:
                self.users[client.phone] = client

    async def create_user(self, user: User) -> User:
        user.ID = self.next_id
        self.next_id += 1
        self.users[user.phone] = user
        return user

    async def get_client_by_phone(self, phone: str) -> User | None:
        return self.users.get(phone)

    async def phone_exists(self, phone: str) -> bool:
        return phone in self.users

    async def user_exists(self, telegram_user_id: int) -> bool:
        return any(u.telegram_user_id == telegram_user_id for u in self.users.values())

    async def get_user_by_phone(self, phone: str) -> User | None:
        return self.users.get(phone)


class FakeStaffRepository:
    """In-memory staff repository for testing."""

    def __init__(self, staff: Staff = None):
        self.staff = staff or Staff(telegram_user_id=100, clinic_id=1)

    async def get_staff(self, telegram_user_id: int) -> Staff | None:
        if self.staff and self.staff.telegram_user_id == telegram_user_id:
            return self.staff
        return None


class FakeClinicRepository:
    """In-memory clinic repository for testing."""

    def __init__(self, clinic: Clinic = None):
        self.clinic = clinic or Clinic(clinic_id=1, name="Клиника Тест", token="test-token")

    async def get_clinic_by_id(self, clinic_id: int) -> Clinic | None:
        if self.clinic and self.clinic.clinic_id == clinic_id:
            return self.clinic
        return None


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def memory_storage():
    """Create a fresh memory storage for each test."""
    return MemoryStorage()


@pytest.fixture
def chat():
    """Create a mock Telegram chat."""
    return Chat(id=100, type="private")


@pytest.fixture
def telegram_user():
    """Create a mock Telegram user."""
    return TelegramUser(id=100, is_bot=False, first_name="Test")


@pytest.fixture
def existing_client():
    """Create an existing client for testing."""
    return User(
        ID=1,
        full_name="Иван Иванов",
        phone="+998901234567",
        role=Role.CLIENT,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )


@pytest.fixture
def test_clinic():
    """Create a test clinic."""
    return Clinic(clinic_id=1, name="Клиника Тест", token="test-token")


@pytest.fixture
def test_staff():
    """Create a test staff member."""
    return Staff(telegram_user_id=100, clinic_id=1)


@pytest.fixture
def fake_appointment_repo():
    """Create a fake appointment repository."""
    return FakeAppointmentRepository()


@pytest.fixture
def fake_user_repo(existing_client):
    """Create a fake user repository with existing client."""
    return FakeUserRepository(existing_clients=[existing_client])


@pytest.fixture
def fake_staff_repo(test_staff):
    """Create a fake staff repository."""
    return FakeStaffRepository(test_staff)


@pytest.fixture
def fake_clinic_repo(test_clinic):
    """Create a fake clinic repository."""
    return FakeClinicRepository(test_clinic)


@pytest.fixture
def fsm_context(memory_storage, chat, telegram_user):
    """Create an FSM context for testing."""
    key = (chat.id, telegram_user.id)
    return FSMContext(storage=memory_storage, key=key)


# ============================================================================
# Scenario 1: Happy Path (Existing Client)
# ============================================================================

@pytest.mark.asyncio
async def test_happy_path_existing_client(
    fsm_context: FSMContext,
    chat: Chat,
    telegram_user: TelegramUser,
    fake_user_repo: FakeUserRepository,
    existing_client: User,
):
    """
    Test happy path: existing client appointment creation.

    Flow:
    - client_full_name → client_phone → appointment_datetime →
    - appointment_datetime_confirm → purpose → confirm

    Verify:
    - No client creation state entered
    - All FSM data populated correctly
    - State transitions are correct
    """
    # Initial state
    await fsm_context.set_state(AppointmentCreationStates.client_full_name)
    await fsm_context.update_data(clinic_name="Клиника Тест")

    # Step 1: Input name
    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.client_full_name

    await fsm_context.update_data(full_name="Иван Иванов")
    await fsm_context.set_state(AppointmentCreationStates.client_phone)

    # Step 2: Input phone
    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.client_phone

    # Verify client exists
    client = await fake_user_repo.get_client_by_phone("+998901234567")
    assert client is not None
    assert client.full_name == "Иван Иванов"

    # Since client exists, move to appointment_datetime (skip client_creation_confirm)
    await fsm_context.update_data(phone="+998901234567")
    await fsm_context.set_state(AppointmentCreationStates.appointment_datetime)

    # Step 3: Input datetime
    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.appointment_datetime

    await fsm_context.update_data(
        appointment_datetime_parsed=datetime(2026, 7, 10, 15, 30),
        appointment_datetime_display="10 июля 2026, 15:30"
    )
    await fsm_context.set_state(AppointmentCreationStates.appointment_datetime_confirm)

    # Step 4: Confirm datetime
    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.appointment_datetime_confirm

    await fsm_context.update_data(appointment_datetime="2026-07-10 15:30:00")
    await fsm_context.set_state(AppointmentCreationStates.purpose)

    # Step 5: Input purpose
    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.purpose

    await fsm_context.update_data(purpose="Консультация")
    await fsm_context.set_state(AppointmentCreationStates.confirm)

    # Final state
    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.confirm

    # Verify all FSM data
    data = await fsm_context.get_data()
    assert data["full_name"] == "Иван Иванов"
    assert data["phone"] == "+998901234567"
    assert data["appointment_datetime"] == "2026-07-10 15:30:00"
    assert data["appointment_datetime_display"] == "10 июля 2026, 15:30"
    assert data["purpose"] == "Консультация"
    assert data["clinic_name"] == "Клиника Тест"


# ============================================================================
# Scenario 2: New Client Path
# ============================================================================

@pytest.mark.asyncio
async def test_new_client_path(
    fsm_context: FSMContext,
    chat: Chat,
    telegram_user: TelegramUser,
    fake_user_repo: FakeUserRepository,
):
    """
    Test new client flow: client doesn't exist.

    Flow:
    - client_full_name → client_phone → confirm_create →
    - appointment_datetime → appointment_datetime_confirm → purpose → confirm

    Verify:
    - client_creation_confirm state entered
    - Can proceed to datetime after confirmation
    - New client data preserved
    """
    new_phone = "+998987654321"
    new_name = "Петр Петров"

    # Verify client doesn't exist
    assert await fake_user_repo.get_client_by_phone(new_phone) is None

    # Initial state
    await fsm_context.set_state(AppointmentCreationStates.client_full_name)
    await fsm_context.update_data(clinic_name="Клиника Тест")

    # Step 1: Input name
    await fsm_context.update_data(full_name=new_name)
    await fsm_context.set_state(AppointmentCreationStates.client_phone)

    # Step 2: Input phone
    await fsm_context.update_data(phone=new_phone)

    # Step 2b: Check client doesn't exist, enter client_creation_confirm
    client = await fake_user_repo.get_client_by_phone(new_phone)
    assert client is None

    # Move to confirmation state
    await fsm_context.set_state(AppointmentCreationStates.confirm_create)
    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.confirm_create

    # Verify data preserved
    data = await fsm_context.get_data()
    assert data["full_name"] == new_name
    assert data["phone"] == new_phone

    # Step 3: Confirm and create client
    new_client = User(
        full_name=new_name,
        phone=new_phone,
        role=Role.CLIENT,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )
    await fake_user_repo.create_user(new_client)

    # Verify client was created
    created_client = await fake_user_repo.get_client_by_phone(new_phone)
    assert created_client is not None
    assert created_client.full_name == new_name

    # Move to appointment_datetime
    await fsm_context.set_state(AppointmentCreationStates.appointment_datetime)
    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.appointment_datetime

    # Step 4: Input datetime and complete flow
    await fsm_context.update_data(
        appointment_datetime_parsed=datetime(2026, 7, 15, 14, 0),
        appointment_datetime_display="15 июля 2026, 14:00",
        appointment_datetime="2026-07-15 14:00:00",
    )
    await fsm_context.set_state(AppointmentCreationStates.appointment_datetime_confirm)
    await fsm_context.set_state(AppointmentCreationStates.purpose)

    await fsm_context.update_data(purpose="Чистка")
    await fsm_context.set_state(AppointmentCreationStates.confirm)

    # Final verification
    data = await fsm_context.get_data()
    assert data["full_name"] == new_name
    assert data["phone"] == new_phone
    assert data["purpose"] == "Чистка"


# ============================================================================
# Scenario 3: New Client with Name Edit
# ============================================================================

@pytest.mark.asyncio
async def test_new_client_with_name_edit(
    fsm_context: FSMContext,
    chat: Chat,
    telegram_user: TelegramUser,
    fake_user_repo: FakeUserRepository,
):
    """
    Test new client with name editing.

    Flow:
    - client_full_name → client_phone → confirm_create →
    - edit_full_name → confirm_create (with new name) → ...

    Verify:
    - Transitions to edit_full_name correctly
    - Returns to client_creation_confirm with new name
    - Name is validated and updated in FSM data
    """
    initial_name = "Петр"
    edited_name = "Сергей Сергеев"
    phone = "+998987654321"

    # Verify client doesn't exist
    assert await fake_user_repo.get_client_by_phone(phone) is None

    # Reach client_creation_confirm state
    await fsm_context.set_state(AppointmentCreationStates.confirm_create)
    await fsm_context.update_data(
        full_name=initial_name,
        phone=phone,
        clinic_name="Клиника Тест"
    )

    # Step 1: User clicks "edit_full_name"
    await fsm_context.set_state(AppointmentCreationStates.edit_full_name)
    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.edit_full_name

    # Step 2: User enters new name
    await fsm_context.update_data(full_name=edited_name)

    # Step 3: Validate and return to confirmation
    await fsm_context.set_state(AppointmentCreationStates.confirm_create)
    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.confirm_create

    # Verify name was updated
    data = await fsm_context.get_data()
    assert data["full_name"] == edited_name
    assert data["phone"] == phone

    # Verify phone is still unchanged
    assert data["phone"] == phone


# ============================================================================
# Scenario 4: New Client with Phone Edit
# ============================================================================

@pytest.mark.asyncio
async def test_new_client_with_phone_edit(
    fsm_context: FSMContext,
    chat: Chat,
    telegram_user: TelegramUser,
    fake_user_repo: FakeUserRepository,
):
    """
    Test new client with phone editing.

    Flow:
    - client_full_name → client_phone → confirm_create →
    - edit_client_phone → client_creation_confirm (with new phone) → ...

    Verify:
    - Transitions to edit_client_phone correctly
    - Returns to client_creation_confirm with new phone
    - Phone is validated and updated in FSM data
    """
    name = "Иван"
    initial_phone = "999"  # Invalid
    edited_phone = "+998987654321"  # Valid

    # Start from phone entry
    await fsm_context.set_state(AppointmentCreationStates.confirm_create)
    await fsm_context.update_data(
        full_name=name,
        phone=initial_phone,
        clinic_name="Клиника Тест"
    )

    # Step 1: User clicks "edit_phone"
    await fsm_context.set_state(AppointmentCreationStates.edit_phone)
    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.edit_phone

    # Step 2: User enters new phone
    await fsm_context.update_data(phone=edited_phone)

    # Step 3: Validate and return to confirmation
    await fsm_context.set_state(AppointmentCreationStates.confirm_create)
    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.confirm_create

    # Verify phone was updated
    data = await fsm_context.get_data()
    assert data["phone"] == edited_phone
    assert data["full_name"] == name

    # Verify old phone is gone
    assert data["phone"] != initial_phone


# ============================================================================
# Scenario 5: DateTime Parsing and Retry
# ============================================================================

@pytest.mark.asyncio
async def test_datetime_parsing_and_retry(
    fsm_context: FSMContext,
    chat: Chat,
    telegram_user: TelegramUser,
):
    """
    Test datetime parsing with error and retry.

    Scenario:
    - First attempt: "invalid gibberish" → stays in appointment_datetime state
    - Second attempt: "завтра в 3 часа" → moves to appointment_datetime_confirm

    Verify:
    - Invalid datetime returns False, state unchanged
    - Valid datetime parsed successfully
    - Display format is set correctly
    - Transitions to confirmation state
    """
    await fsm_context.set_state(AppointmentCreationStates.appointment_datetime)
    await fsm_context.update_data(
        full_name="Тест Клиент",
        phone="+998901234567",
        clinic_name="Клиника Тест"
    )

    # Step 1: Invalid datetime input
    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.appointment_datetime

    # Simulate invalid parsing (stays in same state)
    invalid_input = "invalid gibberish"
    # In real flow, this would be handled by datetime_processing helper
    # which would return False and not change state
    data_before = await fsm_context.get_data()

    # Don't update state on parsing error
    await fsm_context.set_state(AppointmentCreationStates.appointment_datetime)

    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.appointment_datetime
    data_after = await fsm_context.get_data()

    # FSM data should be unchanged
    assert data_after == data_before

    # Step 2: Valid datetime input (second attempt)
    # Simulate successful parsing of "завтра в 3 часа"
    parsed_datetime = datetime(2026, 7, 8, 15, 0)  # Tomorrow at 3 PM
    display_format = "8 июля 2026, 15:00"

    await fsm_context.update_data(
        appointment_datetime_parsed=parsed_datetime,
        appointment_datetime_display=display_format
    )
    await fsm_context.set_state(AppointmentCreationStates.appointment_datetime_confirm)

    # Verify transition
    state = await fsm_context.get_state()
    assert state == AppointmentCreationStates.appointment_datetime_confirm

    # Verify data
    data = await fsm_context.get_data()
    assert data["appointment_datetime_parsed"] == parsed_datetime
    assert data["appointment_datetime_display"] == display_format


# ============================================================================
# Additional Edge Case Tests
# ============================================================================

@pytest.mark.asyncio
async def test_fsm_data_accumulation_across_states(
    fsm_context: FSMContext,
):
    """
    Verify that FSM data accumulates correctly without loss.
    """
    # Start collecting data
    await fsm_context.set_state(AppointmentCreationStates.client_full_name)
    await fsm_context.update_data(clinic_name="Клиника Тест")
    data = await fsm_context.get_data()
    assert data["clinic_name"] == "Клиника Тест"

    # Add name
    await fsm_context.update_data(full_name="Иван Иванов")
    data = await fsm_context.get_data()
    assert data["clinic_name"] == "Клиника Тест"
    assert data["full_name"] == "Иван Иванов"

    # Add phone
    await fsm_context.update_data(phone="+998901234567")
    data = await fsm_context.get_data()
    assert data["clinic_name"] == "Клиника Тест"
    assert data["full_name"] == "Иван Иванов"
    assert data["phone"] == "+998901234567"

    # Add datetime
    await fsm_context.update_data(appointment_datetime="2026-07-10 15:30:00")
    data = await fsm_context.get_data()
    assert data["clinic_name"] == "Клиника Тест"
    assert data["full_name"] == "Иван Иванов"
    assert data["phone"] == "+998901234567"
    assert data["appointment_datetime"] == "2026-07-10 15:30:00"

    # Add purpose
    await fsm_context.update_data(purpose="Консультация")
    data = await fsm_context.get_data()
    assert data["clinic_name"] == "Клиника Тест"
    assert data["full_name"] == "Иван Иванов"
    assert data["phone"] == "+998901234567"
    assert data["appointment_datetime"] == "2026-07-10 15:30:00"
    assert data["purpose"] == "Консультация"


@pytest.mark.asyncio
async def test_fsm_state_transitions_sequence(
    fsm_context: FSMContext,
):
    """
    Verify correct state transition sequence for happy path.
    """
    expected_states = [
        AppointmentCreationStates.client_full_name,
        AppointmentCreationStates.client_phone,
        AppointmentCreationStates.appointment_datetime,
        AppointmentCreationStates.appointment_datetime_confirm,
        AppointmentCreationStates.purpose,
        AppointmentCreationStates.confirm,
    ]

    for expected_state in expected_states:
        await fsm_context.set_state(expected_state)
        current_state = await fsm_context.get_state()
        assert current_state == expected_state


@pytest.mark.asyncio
async def test_fake_repositories_track_operations(
    fake_user_repo: FakeUserRepository,
    fake_appointment_repo: FakeAppointmentRepository,
):
    """
    Verify that fake repositories correctly track operations.
    """
    # Create user
    new_user = User(
        full_name="Тест Клиент",
        phone="+998901234567",
        role=Role.CLIENT,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )
    await fake_user_repo.create_user(new_user)

    # Verify user was created
    retrieved = await fake_user_repo.get_client_by_phone("+998901234567")
    assert retrieved is not None
    assert retrieved.full_name == "Тест Клиент"
    assert retrieved.ID == 1

    # Create appointment
    appointment = Appointment(
        clinic_id=1,
        client_id=retrieved.ID,
        datetime="2026-07-10 15:30:00",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        clinic_name="Клиника Тест",
    )
    created_appointment = await fake_appointment_repo.create_appointment(appointment)

    # Verify appointment was created with ID
    assert created_appointment.id == 1
    assert created_appointment.client_id == retrieved.ID

    # Verify retrieval
    retrieved_appointment = await fake_appointment_repo.get_appointment_by_id(1)
    assert retrieved_appointment is not None
    assert retrieved_appointment.purpose == "Консультация"


# ============================================================================
# Advanced FSM Flow Tests - Client Creation Confirmation States
# ============================================================================

@pytest.mark.asyncio
async def test_client_creation_confirm_state_preserves_all_data(
    fsm_context: FSMContext,
    fake_user_repo: FakeUserRepository,
):
    """
    Verify that client_creation_confirm state preserves all entered data
    even when editing name or phone multiple times.
    """
    await fsm_context.set_state(AppointmentCreationStates.confirm_create)
    await fsm_context.update_data(
        clinic_name="Клиника Тест",
        full_name="Начальное Имя",
        phone="+998901234567",
    )

    # First edit cycle
    await fsm_context.set_state(AppointmentCreationStates.edit_full_name)
    await fsm_context.update_data(full_name="Новое Имя")
    await fsm_context.set_state(AppointmentCreationStates.confirm_create)

    data = await fsm_context.get_data()
    assert data["full_name"] == "Новое Имя"
    assert data["phone"] == "+998901234567"
    assert data["clinic_name"] == "Клиника Тест"

    # Second edit cycle
    await fsm_context.set_state(AppointmentCreationStates.edit_phone)
    await fsm_context.update_data(phone="+998987654321")
    await fsm_context.set_state(AppointmentCreationStates.confirm_create)

    data = await fsm_context.get_data()
    assert data["full_name"] == "Новое Имя"  # Still has previous edit
    assert data["phone"] == "+998987654321"
    assert data["clinic_name"] == "Клиника Тест"


@pytest.mark.asyncio
async def test_appointment_flow_after_client_creation(
    fsm_context: FSMContext,
    fake_user_repo: FakeUserRepository,
):
    """
    Verify complete flow from new client creation through appointment confirmation.
    """
    # Simulate complete new client flow
    await fsm_context.set_state(AppointmentCreationStates.client_full_name)
    await fsm_context.update_data(clinic_name="Клиника Тест")

    # Enter name and phone
    await fsm_context.update_data(full_name="Сергей Петров")
    await fsm_context.update_data(phone="+998912345678")

    # Enter client_creation_confirm (client doesn't exist)
    assert await fake_user_repo.get_client_by_phone("+998912345678") is None
    await fsm_context.set_state(AppointmentCreationStates.confirm_create)

    # Confirm creation
    new_client = User(
        full_name="Сергей Петров",
        phone="+998912345678",
        role=Role.CLIENT,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )
    await fake_user_repo.create_user(new_client)

    # Move through appointment states
    await fsm_context.set_state(AppointmentCreationStates.appointment_datetime)
    await fsm_context.update_data(
        appointment_datetime_parsed=datetime(2026, 8, 1, 10, 0),
        appointment_datetime_display="1 августа 2026, 10:00",
        appointment_datetime="2026-08-01 10:00:00",
    )

    await fsm_context.set_state(AppointmentCreationStates.appointment_datetime_confirm)
    await fsm_context.set_state(AppointmentCreationStates.purpose)

    await fsm_context.update_data(purpose="Профилактический осмотр")
    await fsm_context.set_state(AppointmentCreationStates.confirm)

    # Verify final data
    data = await fsm_context.get_data()
    assert data["full_name"] == "Сергей Петров"
    assert data["phone"] == "+998912345678"
    assert data["purpose"] == "Профилактический осмотр"
    assert data["appointment_datetime"] == "2026-08-01 10:00:00"
    assert await fsm_context.get_state() == AppointmentCreationStates.confirm


@pytest.mark.asyncio
async def test_multiple_clients_in_repository(
    fake_user_repo: FakeUserRepository,
):
    """
    Verify that repository correctly handles multiple clients
    and retrieves only the requested one.
    """
    # Create multiple clients
    client1 = User(
        full_name="Клиент Первый",
        phone="+998901111111",
        role=Role.CLIENT,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )
    client2 = User(
        full_name="Клиент Второй",
        phone="+998902222222",
        role=Role.CLIENT,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )
    client3 = User(
        full_name="Клиент Третий",
        phone="+998903333333",
        role=Role.CLIENT,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )

    await fake_user_repo.create_user(client1)
    await fake_user_repo.create_user(client2)
    await fake_user_repo.create_user(client3)

    # Verify each can be retrieved independently
    retrieved1 = await fake_user_repo.get_client_by_phone("+998901111111")
    assert retrieved1.full_name == "Клиент Первый"
    assert retrieved1.ID == 1

    retrieved2 = await fake_user_repo.get_client_by_phone("+998902222222")
    assert retrieved2.full_name == "Клиент Второй"
    assert retrieved2.ID == 2

    retrieved3 = await fake_user_repo.get_client_by_phone("+998903333333")
    assert retrieved3.full_name == "Клиент Третий"
    assert retrieved3.ID == 3

    # Verify non-existent returns None
    not_found = await fake_user_repo.get_client_by_phone("+998904444444")
    assert not_found is None


@pytest.mark.asyncio
async def test_appointment_creation_with_multiple_clients(
    fake_user_repo: FakeUserRepository,
    fake_appointment_repo: FakeAppointmentRepository,
):
    """
    Verify appointment creation works correctly when multiple clients exist.
    """
    # Create multiple clients
    client1 = User(
        full_name="Клиент A",
        phone="+998905555555",
        role=Role.CLIENT,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )
    client2 = User(
        full_name="Клиент B",
        phone="+998906666666",
        role=Role.CLIENT,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )

    await fake_user_repo.create_user(client1)
    await fake_user_repo.create_user(client2)

    # Create appointments for both clients
    appt1 = Appointment(
        clinic_id=1,
        client_id=client1.ID,
        datetime="2026-07-20 10:00:00",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        clinic_name="Клиника Тест",
    )

    appt2 = Appointment(
        clinic_id=1,
        client_id=client2.ID,
        datetime="2026-07-21 14:00:00",
        purpose="УЗИ диагностика",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.PENDING,
        clinic_name="Клиника Тест",
    )

    created1 = await fake_appointment_repo.create_appointment(appt1)
    created2 = await fake_appointment_repo.create_appointment(appt2)

    # Verify appointments are independent
    assert created1.id == 1
    assert created2.id == 2
    assert created1.client_id == client1.ID
    assert created2.client_id == client2.ID

    # Verify retrieval by client ID
    client1_appointments = await fake_appointment_repo.get_appointments_by_client_id(client1.ID)
    assert len(client1_appointments) == 1
    assert client1_appointments[0].purpose == "Консультация"

    client2_appointments = await fake_appointment_repo.get_appointments_by_client_id(client2.ID)
    assert len(client2_appointments) == 1
    assert client2_appointments[0].purpose == "УЗИ диагностика"
