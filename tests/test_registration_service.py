import pytest

from bot.exceptions.user_exceptions import PhoneAlreadyExistsError, UserAlreadyExistsError
from bot.models.user import User
from bot.services.utils.registration import RegistrationService
from bot.utils.role import Role


@pytest.mark.asyncio
async def test_registration_creates_new_user_when_phone_not_found(fake_user_repo):
    service = RegistrationService(fake_user_repo)

    user = await service.register(
        telegram_user_id=1001,
        full_name="Иванов Иван",
        phone="90 123-45-67",
        role=Role.CLIENT,
        clinic_id=1,
    )

    assert user.phone == "+998901234567"
    assert user.telegram_user_id == 1001
    assert fake_user_repo.created_users == [user]


@pytest.mark.asyncio
async def test_registration_links_existing_user_without_telegram(fake_user_repo_factory):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_phone={"+998901234567": existing})
    service = RegistrationService(repo)

    user = await service.register(
        telegram_user_id=1001,
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        clinic_id=1,
    )

    assert user.ID == 7
    assert user.telegram_user_id == 1001
    assert repo.created_users == []
    assert repo.linked == [(7, 1001)]


@pytest.mark.asyncio
async def test_registration_rejects_existing_user_with_telegram(fake_user_repo_factory):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=555,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_phone={"+998901234567": existing})
    service = RegistrationService(repo)

    with pytest.raises(PhoneAlreadyExistsError):
        await service.register(
            telegram_user_id=1001,
            full_name="Иванов Иван",
            phone="+998901234567",
            role=Role.CLIENT,
            clinic_id=1,
        )


@pytest.mark.asyncio
async def test_registration_rejects_when_telegram_already_registered(fake_user_repo_factory):
    repo = fake_user_repo_factory(existing_telegram_ids={1001})
    service = RegistrationService(repo)

    with pytest.raises(UserAlreadyExistsError):
        await service.register(
            telegram_user_id=1001,
            full_name="Иванов Иван",
            phone="+998901234567",
            role=Role.CLIENT,
            clinic_id=1,
        )
