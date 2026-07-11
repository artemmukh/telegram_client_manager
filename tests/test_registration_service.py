import pytest

from bot.exceptions.user_exceptions import PhoneAlreadyExistsError, UserAlreadyExistsError, UserNotFoundError
from bot.models.user import User
from bot.services.utils.registration import PhoneLookupResult, RegistrationService
from bot.utils.role import Role


@pytest.mark.asyncio
async def test_registration_creates_new_user_when_phone_not_found(fake_user_repo, fake_clinic_repo):
    service = RegistrationService(fake_user_repo, fake_clinic_repo)

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
async def test_registration_links_existing_user_without_telegram(fake_user_repo_factory, fake_clinic_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_phone={"+998901234567": existing})
    service = RegistrationService(repo, fake_clinic_repo)

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
async def test_registration_rejects_existing_user_with_telegram(fake_user_repo_factory, fake_clinic_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=555,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_phone={"+998901234567": existing})
    service = RegistrationService(repo, fake_clinic_repo)

    with pytest.raises(PhoneAlreadyExistsError):
        await service.register(
            telegram_user_id=1001,
            full_name="Иванов Иван",
            phone="+998901234567",
            role=Role.CLIENT,
            clinic_id=1,
        )


@pytest.mark.asyncio
async def test_registration_rejects_when_telegram_already_registered(fake_user_repo_factory, fake_clinic_repo):
    repo = fake_user_repo_factory(existing_telegram_ids={1001})
    service = RegistrationService(repo, fake_clinic_repo)

    with pytest.raises(UserAlreadyExistsError):
        await service.register(
            telegram_user_id=1001,
            full_name="Иванов Иван",
            phone="+998901234567",
            role=Role.CLIENT,
            clinic_id=1,
        )


@pytest.mark.asyncio
async def test_register_with_existing_user_id_links_without_relookup(fake_user_repo_factory, fake_clinic_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_id={7: existing})
    service = RegistrationService(repo, fake_clinic_repo)

    user = await service.register(
        telegram_user_id=1001,
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        clinic_id=1,
        existing_user_id=7,
    )

    assert user.ID == 7
    assert repo.linked == [(7, 1001)]
    assert repo.created_users == []


@pytest.mark.asyncio
async def test_register_with_existing_user_id_syncs_edited_full_name(fake_user_repo_factory, fake_clinic_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_id={7: existing})
    service = RegistrationService(repo, fake_clinic_repo)

    user = await service.register(
        telegram_user_id=1001,
        full_name="Петров Петр",
        phone="+998901234567",
        role=Role.CLIENT,
        clinic_id=1,
        existing_user_id=7,
    )

    assert user.full_name == "Петров Петр"
    assert repo.clients_by_id[7].full_name == "Петров Петр"
    assert repo.updated_clients == [(7, user)]
    assert repo.linked == [(7, 1001)]


@pytest.mark.asyncio
async def test_register_with_existing_user_id_skips_write_when_name_unchanged(
        fake_user_repo_factory, fake_clinic_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_id={7: existing})
    service = RegistrationService(repo, fake_clinic_repo)

    user = await service.register(
        telegram_user_id=1001,
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        clinic_id=1,
        existing_user_id=7,
    )

    assert user.full_name == "Иванов Иван"
    assert repo.updated_clients == []
    assert repo.linked == [(7, 1001)]


@pytest.mark.asyncio
async def test_check_phone_returns_not_found(fake_user_repo, fake_clinic_repo):
    service = RegistrationService(fake_user_repo, fake_clinic_repo)

    result = await service.check_phone("90 123-45-67", telegram_user_id=1001)

    assert result == PhoneLookupResult(status="not_found")


@pytest.mark.asyncio
async def test_check_phone_returns_found_unclaimed(fake_user_repo_factory, fake_clinic_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_phone={"+998901234567": existing})
    service = RegistrationService(repo, fake_clinic_repo)

    result = await service.check_phone("+998901234567", telegram_user_id=1001)

    assert result.status == "found_unclaimed"
    assert result.existing_user is existing


@pytest.mark.asyncio
async def test_check_phone_rejects_already_claimed_phone(fake_user_repo_factory, fake_clinic_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=555,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_phone={"+998901234567": existing})
    service = RegistrationService(repo, fake_clinic_repo)

    with pytest.raises(PhoneAlreadyExistsError):
        await service.check_phone("+998901234567", telegram_user_id=1001)


@pytest.mark.asyncio
async def test_check_phone_rejects_when_telegram_already_registered(fake_user_repo_factory, fake_clinic_repo):
    repo = fake_user_repo_factory(existing_telegram_ids={1001})
    service = RegistrationService(repo, fake_clinic_repo)

    with pytest.raises(UserAlreadyExistsError):
        await service.check_phone("+998901234567", telegram_user_id=1001)


@pytest.mark.asyncio
async def test_apply_name_conflict_resolution_updates_full_name(fake_user_repo_factory, fake_clinic_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_id={7: existing})
    service = RegistrationService(repo, fake_clinic_repo)

    user = await service.apply_name_conflict_resolution(7, "Петров Петр")

    assert user.full_name == "Петров Петр"
    assert repo.updated_clients == [(7, user)]


@pytest.mark.asyncio
async def test_apply_name_conflict_resolution_raises_if_user_not_found(fake_user_repo, fake_clinic_repo):
    service = RegistrationService(fake_user_repo, fake_clinic_repo)

    with pytest.raises(UserNotFoundError):
        await service.apply_name_conflict_resolution(999, "Петров Петр")
