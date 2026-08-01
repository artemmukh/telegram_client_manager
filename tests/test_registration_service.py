from datetime import datetime, timedelta

import pytest

from bot.exceptions.user_exceptions import (
    ContactOwnershipMismatchError,
    InvalidBirthDateError,
    PhoneAlreadyExistsError,
    UserAlreadyExistsError,
    UserNotFoundError,
    ValidationError,
)
from bot.models.user import User
from bot.services.utils.date_parser import get_current_tashkent_time
from bot.services.utils.registration import PhoneLookupResult, RegistrationService
from bot.utils.role import Role


@pytest.mark.asyncio
async def test_registration_creates_new_user_when_phone_not_found(fake_user_repo, fake_clinic_repo, fake_user_settings_repo):
    service = RegistrationService(fake_user_repo, fake_clinic_repo, fake_user_settings_repo)

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
async def test_registration_creates_new_user_with_birth_date_and_gender(fake_user_repo, fake_clinic_repo, fake_user_settings_repo):
    service = RegistrationService(fake_user_repo, fake_clinic_repo, fake_user_settings_repo)

    user = await service.register(
        telegram_user_id=1001,
        full_name="Иванов Иван",
        phone="90 123-45-67",
        role=Role.CLIENT,
        clinic_id=1,
        birth_date="05.03.1990",
        gender="male",
    )

    assert user.birth_date == "1990-03-05"
    assert user.gender == "male"
    assert fake_user_repo.created_users == [user]
    assert fake_user_repo.created_users[0].birth_date == "1990-03-05"
    assert fake_user_repo.created_users[0].gender == "male"


@pytest.mark.asyncio
async def test_registration_creates_new_user_without_birth_date_and_gender_defaults_to_none(
        fake_user_repo, fake_clinic_repo, fake_user_settings_repo):
    # Existing (pre-birth_date/gender feature) call sites keep working exactly
    # as before: both fields default to None and are persisted as None, not
    # silently coerced into anything else.
    service = RegistrationService(fake_user_repo, fake_clinic_repo, fake_user_settings_repo)

    user = await service.register(
        telegram_user_id=1001,
        full_name="Иванов Иван",
        phone="90 123-45-67",
        role=Role.CLIENT,
        clinic_id=1,
    )

    assert user.birth_date is None
    assert user.gender is None
    assert fake_user_repo.created_users[0].birth_date is None
    assert fake_user_repo.created_users[0].gender is None


@pytest.mark.asyncio
async def test_register_rejects_invalid_gender_value(fake_user_repo, fake_clinic_repo, fake_user_settings_repo):
    service = RegistrationService(fake_user_repo, fake_clinic_repo, fake_user_settings_repo)

    with pytest.raises(ValidationError) as exc_info:
        await service.register(
            telegram_user_id=1001,
            full_name="Иванов Иван",
            phone="90 123-45-67",
            role=Role.CLIENT,
            clinic_id=1,
            gender="other",
        )

    assert type(exc_info.value) is ValidationError
    assert fake_user_repo.created_users == []


@pytest.mark.asyncio
async def test_registration_never_rebinds_via_phone_lookup_when_no_existing_user_id(
        fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    # A brand-new registration (existing_user_id=None) must never silently bind
    # an unrelated, unclaimed record by phone. That rebinding is only ever
    # allowed through the verified existing_user_id path, which requires
    # check_phone() to have already confirmed contact ownership. Seed a
    # phone-matching, telegram-unlinked record (ID 7) that the OLD, unsafe
    # register() would have found via get_client_by_phone and silently bound
    # to this new telegram_user_id. register() must instead ignore it
    # entirely and create a fresh user.
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_phone={"+998901234567": existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    user = await service.register(
        telegram_user_id=1001,
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        clinic_id=1,
    )

    assert user.ID != 7
    assert user.telegram_user_id == 1001
    assert repo.created_users == [user]
    assert repo.linked == []


@pytest.mark.asyncio
async def test_registration_rejects_existing_user_with_telegram(fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    # The phone is already taken by a real row in the users table (mirrored
    # here by existing_phones, the fake's analog of the UNIQUE constraint on
    # users.phone). A brand-new registration attempt must surface this as
    # PhoneAlreadyExistsError from create_user, not from any lookup inside
    # register() itself.
    repo = fake_user_repo_factory(existing_phones={"+998901234567"})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    with pytest.raises(PhoneAlreadyExistsError):
        await service.register(
            telegram_user_id=1001,
            full_name="Иванов Иван",
            phone="+998901234567",
            role=Role.CLIENT,
            clinic_id=1,
        )

    assert repo.linked == []


@pytest.mark.asyncio
async def test_registration_rejects_when_telegram_already_registered(fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    repo = fake_user_repo_factory(existing_telegram_ids={1001})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    with pytest.raises(UserAlreadyExistsError):
        await service.register(
            telegram_user_id=1001,
            full_name="Иванов Иван",
            phone="+998901234567",
            role=Role.CLIENT,
            clinic_id=1,
        )


@pytest.mark.asyncio
async def test_register_with_existing_user_id_links_without_relookup(fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_id={7: existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

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
async def test_register_with_existing_user_id_syncs_edited_full_name(fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_id={7: existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

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
        fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_id={7: existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

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
async def test_register_with_existing_user_id_persists_birth_date_and_gender(
        fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_id={7: existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    user = await service.register(
        telegram_user_id=1001,
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        clinic_id=1,
        existing_user_id=7,
        birth_date="05.03.1990",
        gender="male",
    )

    assert user.birth_date == "1990-03-05"
    assert user.gender == "male"
    assert repo.linked == [(7, 1001)]
    # update_user_telegram_id must have actually written both fields, not just
    # the returned User object mirroring them.
    assert repo.clients_by_id[7].birth_date == "1990-03-05"
    assert repo.clients_by_id[7].gender == "male"


@pytest.mark.asyncio
async def test_register_with_existing_user_id_without_birth_date_and_gender_persists_none(
        fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_id={7: existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    user = await service.register(
        telegram_user_id=1001,
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        clinic_id=1,
        existing_user_id=7,
    )

    assert user.birth_date is None
    assert user.gender is None
    assert repo.clients_by_id[7].birth_date is None
    assert repo.clients_by_id[7].gender is None


@pytest.mark.asyncio
async def test_register_with_existing_user_id_rejects_invalid_birth_date_without_claiming_telegram_id(
        fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    # birth_date/gender validation runs before either branch of register()
    # touches the repository, so an invalid birth_date must keep a reclaimed
    # registration atomic: no telegram_user_id claim happens at all.
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_id={7: existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    with pytest.raises(InvalidBirthDateError):
        await service.register(
            telegram_user_id=1001,
            full_name="Иванов Иван",
            phone="+998901234567",
            role=Role.CLIENT,
            clinic_id=1,
            existing_user_id=7,
            birth_date="not-a-date",
        )

    assert repo.linked == []
    assert existing.telegram_user_id is None


@pytest.mark.asyncio
async def test_register_with_existing_user_id_rejects_future_birth_date_without_claiming_telegram_id(
        fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_id={7: existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    now = datetime.strptime(get_current_tashkent_time(), "%Y-%m-%d %H:%M:%S")
    future_date = (now + timedelta(days=1)).strftime("%d.%m.%Y")

    with pytest.raises(InvalidBirthDateError):
        await service.register(
            telegram_user_id=1001,
            full_name="Иванов Иван",
            phone="+998901234567",
            role=Role.CLIENT,
            clinic_id=1,
            existing_user_id=7,
            birth_date=future_date,
        )

    assert repo.linked == []
    assert existing.telegram_user_id is None


@pytest.mark.asyncio
async def test_register_with_existing_user_id_rejects_age_over_120_years_without_claiming_telegram_id(
        fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_id={7: existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    now = datetime.strptime(get_current_tashkent_time(), "%Y-%m-%d %H:%M:%S")
    too_old_date = now.replace(year=now.year - 121).strftime("%d.%m.%Y")

    with pytest.raises(InvalidBirthDateError):
        await service.register(
            telegram_user_id=1001,
            full_name="Иванов Иван",
            phone="+998901234567",
            role=Role.CLIENT,
            clinic_id=1,
            existing_user_id=7,
            birth_date=too_old_date,
        )

    assert repo.linked == []
    assert existing.telegram_user_id is None


@pytest.mark.asyncio
async def test_register_rejects_future_birth_date_for_new_user(fake_user_repo, fake_clinic_repo, fake_user_settings_repo):
    service = RegistrationService(fake_user_repo, fake_clinic_repo, fake_user_settings_repo)

    now = datetime.strptime(get_current_tashkent_time(), "%Y-%m-%d %H:%M:%S")
    future_date = (now + timedelta(days=1)).strftime("%d.%m.%Y")

    with pytest.raises(InvalidBirthDateError):
        await service.register(
            telegram_user_id=1001,
            full_name="Иванов Иван",
            phone="90 123-45-67",
            role=Role.CLIENT,
            clinic_id=1,
            birth_date=future_date,
        )

    assert fake_user_repo.created_users == []


@pytest.mark.asyncio
async def test_register_rejects_age_over_120_years_for_new_user(fake_user_repo, fake_clinic_repo, fake_user_settings_repo):
    service = RegistrationService(fake_user_repo, fake_clinic_repo, fake_user_settings_repo)

    now = datetime.strptime(get_current_tashkent_time(), "%Y-%m-%d %H:%M:%S")
    too_old_date = now.replace(year=now.year - 121).strftime("%d.%m.%Y")

    with pytest.raises(InvalidBirthDateError):
        await service.register(
            telegram_user_id=1001,
            full_name="Иванов Иван",
            phone="90 123-45-67",
            role=Role.CLIENT,
            clinic_id=1,
            birth_date=too_old_date,
        )

    assert fake_user_repo.created_users == []


@pytest.mark.asyncio
async def test_check_phone_returns_not_found(fake_user_repo, fake_clinic_repo, fake_user_settings_repo):
    service = RegistrationService(fake_user_repo, fake_clinic_repo, fake_user_settings_repo)

    result = await service.check_phone("90 123-45-67", telegram_user_id=1001)

    assert result == PhoneLookupResult(status="not_found")


@pytest.mark.asyncio
async def test_check_phone_returns_found_unclaimed(fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_phone={"+998901234567": existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    result = await service.check_phone("+998901234567", telegram_user_id=1001, contact_user_id=1001)

    assert result.status == "found_unclaimed"
    assert result.existing_user is existing


@pytest.mark.asyncio
async def test_check_phone_rejects_mismatched_contact_owner_for_found_unclaimed(
        fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_phone={"+998901234567": existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    with pytest.raises(ContactOwnershipMismatchError):
        await service.check_phone(
            "+998901234567", telegram_user_id=1001, contact_user_id=2002,
        )


@pytest.mark.asyncio
async def test_check_phone_allows_matching_contact_owner_for_found_unclaimed(
        fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_phone={"+998901234567": existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    result = await service.check_phone(
        "+998901234567", telegram_user_id=1001, contact_user_id=1001,
    )

    assert result.status == "found_unclaimed"
    assert result.existing_user is existing


@pytest.mark.asyncio
async def test_check_phone_rejects_found_unclaimed_when_contact_owner_unknown(
        fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_phone={"+998901234567": existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    with pytest.raises(ContactOwnershipMismatchError):
        await service.check_phone("+998901234567", telegram_user_id=1001)


@pytest.mark.asyncio
async def test_check_phone_not_found_ignores_mismatched_contact_owner(
        fake_user_repo, fake_clinic_repo, fake_user_settings_repo):
    service = RegistrationService(fake_user_repo, fake_clinic_repo, fake_user_settings_repo)

    result = await service.check_phone(
        "90 123-45-67", telegram_user_id=1001, contact_user_id=2002,
    )

    assert result == PhoneLookupResult(status="not_found")


@pytest.mark.asyncio
async def test_check_phone_rejects_already_claimed_phone(fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=555,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_phone={"+998901234567": existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    with pytest.raises(PhoneAlreadyExistsError):
        await service.check_phone("+998901234567", telegram_user_id=1001)


@pytest.mark.asyncio
async def test_check_phone_rejects_when_telegram_already_registered(fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    repo = fake_user_repo_factory(existing_telegram_ids={1001})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    with pytest.raises(UserAlreadyExistsError):
        await service.check_phone("+998901234567", telegram_user_id=1001)


@pytest.mark.asyncio
async def test_apply_name_conflict_resolution_updates_full_name(fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_id={7: existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    user = await service.apply_name_conflict_resolution(7, "Петров Петр")

    assert user.full_name == "Петров Петр"
    assert repo.updated_clients == [(7, user)]


@pytest.mark.asyncio
async def test_apply_name_conflict_resolution_raises_if_user_not_found(fake_user_repo, fake_clinic_repo, fake_user_settings_repo):
    service = RegistrationService(fake_user_repo, fake_clinic_repo, fake_user_settings_repo)

    with pytest.raises(UserNotFoundError):
        await service.apply_name_conflict_resolution(999, "Петров Петр")


# --- language persistence ---

@pytest.mark.asyncio
async def test_register_new_user_persists_chosen_language(fake_user_repo, fake_clinic_repo, fake_user_settings_repo):
    service = RegistrationService(fake_user_repo, fake_clinic_repo, fake_user_settings_repo)

    user = await service.register(
        telegram_user_id=1001,
        full_name="Иванов Иван",
        phone="90 123-45-67",
        role=Role.CLIENT,
        clinic_id=1,
        language="uz",
    )

    assert fake_user_settings_repo.language_updates == [(user.ID, "uz")]


@pytest.mark.asyncio
async def test_register_new_user_defaults_language_to_ru_when_omitted(
        fake_user_repo, fake_clinic_repo, fake_user_settings_repo):
    service = RegistrationService(fake_user_repo, fake_clinic_repo, fake_user_settings_repo)

    user = await service.register(
        telegram_user_id=1001,
        full_name="Иванов Иван",
        phone="90 123-45-67",
        role=Role.CLIENT,
        clinic_id=1,
    )

    assert fake_user_settings_repo.language_updates == [(user.ID, "ru")]


@pytest.mark.asyncio
async def test_register_with_existing_user_id_persists_chosen_language(
        fake_user_repo_factory, fake_clinic_repo, fake_user_settings_repo):
    existing = User(
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=None,
        ID=7,
    )
    repo = fake_user_repo_factory(clients_by_id={7: existing})
    service = RegistrationService(repo, fake_clinic_repo, fake_user_settings_repo)

    await service.register(
        telegram_user_id=1001,
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        clinic_id=1,
        existing_user_id=7,
        language="uz",
    )

    assert fake_user_settings_repo.language_updates == [(7, "uz")]
