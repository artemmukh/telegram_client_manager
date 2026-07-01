import importlib

import pytest

from bot.exceptions.user_exceptions import PhoneAlreadyExistsError, UserAlreadyExistsError
from bot.services.utils.registration import RegistrationService
from bot.utils.role import Role


@pytest.mark.asyncio
async def test_registration_service_registers_new_user(fake_user_repo):
    service = RegistrationService(fake_user_repo)

    user = await service.register(
        telegram_user_id=1001,
        full_name="\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
        phone="90 123-45-67",
        role=Role.CLIENT,
    )

    assert user.full_name == "\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d"
    assert user.phone == "+998901234567"
    assert user.telegram_user_id == 1001
    assert user.role is Role.CLIENT
    assert fake_user_repo.created_users == [user]


@pytest.mark.asyncio
async def test_registration_service_rejects_duplicate_phone(fake_user_repo_factory):
    repo = fake_user_repo_factory(existing_phones={"+998901234567"})
    service = RegistrationService(repo)

    with pytest.raises(PhoneAlreadyExistsError):
        await service.register(
            telegram_user_id=1001,
            full_name="\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
            phone="+998901234567",
            role=Role.CLIENT,
        )


@pytest.mark.asyncio
async def test_registration_service_rejects_duplicate_telegram_id(fake_user_repo_factory):
    repo = fake_user_repo_factory(existing_telegram_ids={1001})
    service = RegistrationService(repo)

    with pytest.raises(UserAlreadyExistsError):
        await service.register(
            telegram_user_id=1001,
            full_name="\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
            phone="+998901234567",
            role=Role.CLIENT,
        )


def test_auth_service_detects_admin_role(monkeypatch):
    monkeypatch.setenv("ADMIN_IDS", "1001,1002")

    import bot.config.config as config_module
    import bot.services.utils.auth as auth_module

    importlib.reload(config_module)
    auth_module = importlib.reload(auth_module)

    assert auth_module.AuthService.detect_role(1001) is Role.ADMIN
    assert auth_module.AuthService.detect_role(2001) is Role.CLIENT
