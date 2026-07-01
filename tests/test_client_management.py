import pytest

from bot.exceptions.user_exceptions import InvalidFullNameError, PhoneAlreadyExistsError
from bot.services.client.client_management import ClientManagement
from bot.utils.role import Role


@pytest.mark.asyncio
async def test_client_management_creates_client(fake_user_repo):
    service = ClientManagement(fake_user_repo)

    user = await service.create_client(
        {
            "full_name": "  \u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d  ",
            "phone": "90 123-45-67",
        }
    )

    assert user.full_name == "\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d"
    assert user.phone == "+998901234567"
    assert user.role is Role.CLIENT
    assert user.telegram_user_id is None
    assert fake_user_repo.created_users == [user]


@pytest.mark.asyncio
async def test_client_management_rejects_duplicate_phone(fake_user_repo_factory):
    repo = fake_user_repo_factory(existing_phones={"+998901234567"})
    service = ClientManagement(repo)

    with pytest.raises(PhoneAlreadyExistsError):
        await service.create_client(
            {
                "full_name": "\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
                "phone": "+998901234567",
            }
        )


@pytest.mark.asyncio
async def test_client_management_rejects_invalid_name(fake_user_repo):
    service = ClientManagement(fake_user_repo)

    with pytest.raises(InvalidFullNameError):
        await service.create_client({"full_name": "Ivan Ivan", "phone": "+998901234567"})
