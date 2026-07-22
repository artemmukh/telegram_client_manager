import pytest

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import (
    InvalidFullNameError,
    PhoneAlreadyExistsError,
    RoleError,
    UserNotFoundError,
    ValidationError,
)
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.services.client.client_management import ClientManagement
from bot.utils.role import Role


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


def _service(user_repo, clinic_id=1, client_clinic_repo=None, user_settings_repo=None):
    return ClientManagement(
        user_repo,
        FakeStaffRepo(Staff(telegram_user_id=100, clinic_id=clinic_id)),
        FakeClinicRepo(Clinic(clinic_id=clinic_id, name="Зуб Мудрости", token="t")),
        client_clinic_repository=client_clinic_repo,
        user_settings_repository=user_settings_repo,
    )


@pytest.mark.asyncio
async def test_client_management_creates_client(fake_user_repo):
    service = _service(fake_user_repo)

    user = await service.create_client(
        100,
        {
            "full_name": "  Иванов Иван  ",
            "phone": "90 123-45-67",
        },
    )

    assert user.full_name == "Иванов Иван"
    assert user.phone == "+998901234567"
    assert user.role is Role.CLIENT
    assert user.telegram_user_id is None
    assert user.clinic_id == 1
    assert user.clinic_name == "Зуб Мудрости"
    assert fake_user_repo.created_users == [user]


@pytest.mark.asyncio
async def test_client_management_rejects_duplicate_phone(fake_user_repo_factory):
    repo = fake_user_repo_factory(existing_phones={"+998901234567"})
    service = _service(repo)

    with pytest.raises(PhoneAlreadyExistsError):
        await service.create_client(
            100,
            {
                "full_name": "Иванов Иван",
                "phone": "+998901234567",
            },
        )


@pytest.mark.asyncio
async def test_client_management_rejects_invalid_name(fake_user_repo):
    service = _service(fake_user_repo)

    with pytest.raises(InvalidFullNameError):
        await service.create_client(100, {"full_name": "Ivan Ivan", "phone": "+998901234567"})


@pytest.mark.asyncio
async def test_client_management_rejects_non_staff(fake_user_repo):
    service = ClientManagement(fake_user_repo, FakeStaffRepo(None), FakeClinicRepo(None))

    with pytest.raises(RoleError):
        await service.create_client(100, {"full_name": "Иванов Иван", "phone": "+998901234567"})


def _existing_client(user_id=1):
    return User(
        ID=user_id,
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        reminder_24h=True,
        reminder_2h=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "preset, expected_24h, expected_2h",
    [
        ("both", True, True),
        ("24_only", True, False),
        ("2_only", False, True),
        ("off", False, False),
    ],
)
async def test_update_reminder_preferences_maps_preset_to_booleans(
    fake_user_repo_factory, fake_user_settings_repo_factory, preset, expected_24h, expected_2h
):
    repo = fake_user_repo_factory(clients_by_id={1: _existing_client()})
    settings_repo = fake_user_settings_repo_factory()
    service = _service(repo, user_settings_repo=settings_repo)

    user = await service.update_reminder_preferences(1, preset)

    assert user.reminder_24h is expected_24h
    assert user.reminder_2h is expected_2h
    assert settings_repo.updates == [(1, expected_24h, expected_2h)]


@pytest.mark.asyncio
async def test_update_reminder_preferences_rejects_unknown_preset(fake_user_repo_factory):
    repo = fake_user_repo_factory(clients_by_id={1: _existing_client()})
    service = _service(repo)

    with pytest.raises(ValidationError):
        await service.update_reminder_preferences(1, "invalid")


@pytest.mark.asyncio
async def test_update_reminder_preferences_raises_if_client_not_found(fake_user_repo):
    service = _service(fake_user_repo)

    with pytest.raises(UserNotFoundError) as exc_info:
        await service.update_reminder_preferences(999, "both")

    assert str(exc_info.value) == "Пользователь не найден."


def _existing_admin(user_id=2):
    return User(
        ID=user_id,
        full_name="Админов Админ",
        phone="+998907654321",
        role=Role.ADMIN,
        reminder_24h=True,
        reminder_2h=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "preset, expected_24h, expected_2h",
    [
        ("both", True, True),
        ("2_only", False, True),
        ("off", False, False),
    ],
)
async def test_update_reminder_preferences_works_for_admin_user_id(
    fake_user_repo_factory, fake_user_settings_repo_factory, preset, expected_24h, expected_2h
):
    """update_reminder_preferences() now resolves via get_user_by_id(), which is
    role-agnostic, so it must also work for an admin's user_id (not just clients).
    The admin is intentionally absent from clients_by_id to prove the lookup
    does not go through get_client_by_id."""
    admin = _existing_admin()
    repo = fake_user_repo_factory(users_by_id={2: admin})
    settings_repo = fake_user_settings_repo_factory()
    service = _service(repo, user_settings_repo=settings_repo)

    user = await service.update_reminder_preferences(2, preset)

    assert user.role is Role.ADMIN
    assert user.reminder_24h is expected_24h
    assert user.reminder_2h is expected_2h
    assert settings_repo.updates == [(2, expected_24h, expected_2h)]


@pytest.mark.asyncio
async def test_request_name_change_sets_pending_full_name(fake_user_repo_factory):
    repo = fake_user_repo_factory(clients_by_id={1: _existing_client()})
    service = _service(repo)

    user = await service.request_name_change(1, "  Петров Петр  ")

    assert user.pending_full_name == "Петров Петр"


@pytest.mark.asyncio
async def test_request_name_change_rejects_invalid_name(fake_user_repo_factory):
    repo = fake_user_repo_factory(clients_by_id={1: _existing_client()})
    service = _service(repo)

    with pytest.raises(InvalidFullNameError):
        await service.request_name_change(1, "Ivan Ivan")


@pytest.mark.asyncio
async def test_approve_name_change_applies_pending_full_name(
    fake_user_repo_factory, fake_client_clinic_repo_factory,
):
    client = _existing_client()
    client.pending_full_name = "Петров Петр"
    repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, 1)})
    service = _service(repo, client_clinic_repo=client_clinic_repo)

    user = await service.approve_name_change(1, 1)

    assert user.full_name == "Петров Петр"
    assert user.pending_full_name is None


@pytest.mark.asyncio
async def test_reject_name_change_clears_pending_full_name(
    fake_user_repo_factory, fake_client_clinic_repo_factory,
):
    client = _existing_client()
    client.pending_full_name = "Петров Петр"
    repo = fake_user_repo_factory(clients_by_id={1: client})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, 1)})
    service = _service(repo, client_clinic_repo=client_clinic_repo)

    user = await service.reject_name_change(1, 1)

    assert user.full_name == "Иванов Иван"
    assert user.pending_full_name is None


@pytest.mark.asyncio
async def test_approve_name_change_returns_none_when_already_resolved(
    fake_user_repo_factory, fake_client_clinic_repo_factory,
):
    repo = fake_user_repo_factory(clients_by_id={1: _existing_client()})
    client_clinic_repo = fake_client_clinic_repo_factory(links={(1, 1)})
    service = _service(repo, client_clinic_repo=client_clinic_repo)

    result = await service.approve_name_change(1, 1)

    assert result is None


# --- find_clients_by_exact_name ---

@pytest.mark.asyncio
async def test_find_clients_by_exact_name_returns_matches(fake_user_repo_factory):
    existing = _existing_client()
    repo = fake_user_repo_factory(clients_by_exact_name={("Иванов Иван", 1): [existing]})
    service = _service(repo)

    result = await service.find_clients_by_exact_name("  Иванов Иван  ", 1)

    assert result == [existing]


@pytest.mark.asyncio
async def test_find_clients_by_exact_name_returns_empty_list_without_raising(fake_user_repo):
    service = _service(fake_user_repo)

    result = await service.find_clients_by_exact_name("Иванов Иван", 1)

    assert result == []


# --- count_client_appointments ---

class FakeAppointmentRepo:
    def __init__(self, count=0):
        self.count = count
        self.calls = []

    async def count_appointments_by_client_id(self, client_id, clinic_id):
        self.calls.append((client_id, clinic_id))
        return self.count


@pytest.mark.asyncio
async def test_count_client_appointments_returns_repository_count(fake_user_repo):
    appointment_repo = FakeAppointmentRepo(count=3)
    service = ClientManagement(
        fake_user_repo,
        FakeStaffRepo(),
        FakeClinicRepo(),
        appointment_repo,
    )

    result = await service.count_client_appointments(1, 1)

    assert result == 3
    assert appointment_repo.calls == [(1, 1)]


@pytest.mark.asyncio
async def test_count_client_appointments_raises_when_repository_not_wired(fake_user_repo):
    service = _service(fake_user_repo)

    with pytest.raises(BotException):
        await service.count_client_appointments(1, 1)
