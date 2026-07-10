import pytest

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


def _service(user_repo, clinic_id=1):
    return ClientManagement(
        user_repo,
        FakeStaffRepo(Staff(telegram_user_id=100, clinic_id=clinic_id)),
        FakeClinicRepo(Clinic(clinic_id=clinic_id, name="Зуб Мудрости", token="t")),
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
    fake_user_repo_factory, preset, expected_24h, expected_2h
):
    repo = fake_user_repo_factory(clients_by_id={1: _existing_client()})
    service = _service(repo)

    user = await service.update_reminder_preferences(1, preset)

    assert user.reminder_24h is expected_24h
    assert user.reminder_2h is expected_2h
    assert repo.reminder_updates == [(1, expected_24h, expected_2h)]


@pytest.mark.asyncio
async def test_update_reminder_preferences_rejects_unknown_preset(fake_user_repo_factory):
    repo = fake_user_repo_factory(clients_by_id={1: _existing_client()})
    service = _service(repo)

    with pytest.raises(ValidationError):
        await service.update_reminder_preferences(1, "invalid")


@pytest.mark.asyncio
async def test_update_reminder_preferences_raises_if_client_not_found(fake_user_repo):
    service = _service(fake_user_repo)

    with pytest.raises(UserNotFoundError):
        await service.update_reminder_preferences(999, "both")
