import pytest

from bot.exceptions.user_exceptions import InvalidFullNameError, PhoneAlreadyExistsError, RoleError
from bot.models.clinic import Clinic
from bot.models.staff import Staff
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
