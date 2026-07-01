import pytest
import pytest_asyncio

from bot.exceptions.user_exceptions import UserAlreadyExistsError
from bot.models.user import User
from bot.repositories.user_repository import UserRepository
from bot.utils.role import Role


@pytest_asyncio.fixture
async def user_repo(tmp_path):
    repo = UserRepository(str(tmp_path / "test.db"))
    await repo.init()
    return repo


@pytest.mark.asyncio
async def test_user_repository_creates_and_reads_user_by_phone_and_telegram_id(user_repo):
    user = User(
        full_name="\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=1001,
    )

    await user_repo.create_user(user)

    by_phone = await user_repo.get_user_by_phone("+998901234567")
    by_telegram = await user_repo.get_user_by_telegram_id(1001)

    assert by_phone is not None
    assert by_phone.ID is not None
    assert by_phone.full_name == user.full_name
    assert by_phone.phone == user.phone
    assert by_phone.role == Role.CLIENT.value
    assert by_telegram == by_phone
    assert await user_repo.phone_exists("+998901234567") is True
    assert await user_repo.user_exists(1001) is True
    assert await user_repo.get_user_role(1001) == Role.CLIENT.value


@pytest.mark.asyncio
async def test_user_repository_updates_user(user_repo):
    await user_repo.create_user(
        User(
            full_name="\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
            phone="+998901234567",
            role=Role.CLIENT,
            telegram_user_id=1001,
        )
    )

    updated = User(
        full_name="\u041f\u0435\u0442\u0440\u043e\u0432 \u041f\u0435\u0442\u0440",
        phone="+998901234568",
        role=Role.ADMIN,
    )
    await user_repo.update_user(1001, updated)

    user = await user_repo.get_user_by_telegram_id(1001)

    assert user.full_name == updated.full_name
    assert user.phone == updated.phone
    assert user.role == Role.ADMIN.value


@pytest.mark.asyncio
async def test_user_repository_deletes_user(user_repo):
    await user_repo.create_user(
        User(
            full_name="\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
            phone="+998901234567",
            role=Role.CLIENT,
            telegram_user_id=1001,
        )
    )

    await user_repo.delete_user(1001)

    assert await user_repo.get_user_by_telegram_id(1001) is None
    assert await user_repo.user_exists(1001) is False
    assert await user_repo.phone_exists("+998901234567") is False


@pytest.mark.asyncio
async def test_user_repository_searches_users_by_name(user_repo):
    full_name = "\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d"
    await user_repo.create_user(
        User(full_name=full_name, phone="+998901234567", role=Role.CLIENT, telegram_user_id=1001)
    )
    await user_repo.create_user(
        User(full_name=full_name, phone="+998901234568", role=Role.CLIENT, telegram_user_id=1002)
    )

    users = await user_repo.get_user_by_name(full_name)

    assert [user.phone for user in users] == ["+998901234567", "+998901234568"]


@pytest.mark.asyncio
async def test_user_repository_enforces_unique_phone(user_repo):
    await user_repo.create_user(
        User(
            full_name="\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d",
            phone="+998901234567",
            role=Role.CLIENT,
            telegram_user_id=1001,
        )
    )

    with pytest.raises(UserAlreadyExistsError):
        await user_repo.create_user(
            User(
                full_name="\u041f\u0435\u0442\u0440\u043e\u0432 \u041f\u0435\u0442\u0440",
                phone="+998901234567",
                role=Role.CLIENT,
                telegram_user_id=1002,
            )
        )
