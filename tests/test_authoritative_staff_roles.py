from types import SimpleNamespace

import pytest

from bot.middlewares.user import UserContextMiddleware
from bot.models.staff import Staff
from bot.models.user import User
from bot.services.utils.auth import AuthService
from bot.utils.role import Role, RoleFilter


class FakeStaffRepository:
    """Minimal async StaffRepository replacement for role-resolution tests."""

    def __init__(self, staff: Staff | None = None):
        self.staff = staff

    async def get_staff(self, telegram_user_id: int) -> Staff | None:
        if self.staff is not None and self.staff.telegram_user_id == telegram_user_id:
            return self.staff
        return None


class FakeRoleUserRepository:
    """Minimal registered-user repository for filter and middleware tests."""

    def __init__(self, user: User | None):
        self.user = user

    async def user_exists(self, telegram_user_id: int) -> bool:
        return self.user is not None and self.user.telegram_user_id == telegram_user_id

    async def get_user_by_telegram_id(self, telegram_user_id: int) -> User | None:
        if self.user is not None and self.user.telegram_user_id == telegram_user_id:
            return self.user
        return None


def _user(*, telegram_user_id: int | None = 10, clinic_id: int | None = 1, role: Role = Role.CLIENT) -> User:
    return User(
        full_name="U",
        phone="+998",
        role=role,
        telegram_user_id=telegram_user_id,
        clinic_id=clinic_id,
    )


@pytest.mark.asyncio
async def test_resolve_current_role_promotes_registered_client_with_matching_staff():
    auth = AuthService(FakeStaffRepository(Staff(telegram_user_id=10, clinic_id=1)))

    assert await auth.resolve_current_role(_user()) is Role.ADMIN


@pytest.mark.asyncio
async def test_resolve_current_role_is_client_when_staff_is_absent():
    auth = AuthService(FakeStaffRepository())

    assert await auth.resolve_current_role(_user(role=Role.ADMIN)) is Role.CLIENT


@pytest.mark.asyncio
async def test_resolve_current_role_is_client_when_staff_belongs_to_another_clinic():
    auth = AuthService(FakeStaffRepository(Staff(telegram_user_id=10, clinic_id=2)))

    assert await auth.resolve_current_role(_user(role=Role.ADMIN)) is Role.CLIENT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("telegram_user_id", "clinic_id"),
    [(None, 1), (10, None)],
)
async def test_resolve_current_role_is_client_for_missing_persisted_user_fields(
    telegram_user_id: int | None,
    clinic_id: int | None,
):
    auth = AuthService(FakeStaffRepository(Staff(telegram_user_id=10, clinic_id=1)))

    assert await auth.resolve_current_role(_user(telegram_user_id=telegram_user_id, clinic_id=clinic_id)) is Role.CLIENT


@pytest.mark.asyncio
async def test_resolve_current_role_returns_none_for_missing_user():
    auth = AuthService(FakeStaffRepository(Staff(telegram_user_id=10, clinic_id=1)))

    assert await auth.resolve_current_role(None) is None


@pytest.mark.asyncio
async def test_role_filter_allows_registered_cached_client_with_matching_staff_into_admin():
    user_repo = FakeRoleUserRepository(_user(role=Role.CLIENT))
    auth = AuthService(FakeStaffRepository(Staff(telegram_user_id=10, clinic_id=1)))
    message = SimpleNamespace(from_user=SimpleNamespace(id=10))

    assert await RoleFilter("admin")(message, user_repo, auth) == {"role": Role.ADMIN}


@pytest.mark.asyncio
async def test_user_context_middleware_replaces_stale_cached_role_with_authoritative_role():
    user_repo = FakeRoleUserRepository(_user(role=Role.CLIENT))
    auth = AuthService(FakeStaffRepository(Staff(telegram_user_id=10, clinic_id=1)))
    middleware = UserContextMiddleware(user_repo, auth)
    event = SimpleNamespace(from_user=SimpleNamespace(id=10))
    data: dict = {}

    async def handler(_event, handler_data):
        return handler_data

    result = await middleware(handler, event, data)

    assert result["current_user"].role is Role.ADMIN
    assert user_repo.user.role is Role.CLIENT


@pytest.mark.asyncio
async def test_role_filter_denies_registered_cached_admin_without_matching_staff():
    user_repo = FakeRoleUserRepository(_user(role=Role.ADMIN))
    auth = AuthService(FakeStaffRepository())
    message = SimpleNamespace(from_user=SimpleNamespace(id=10))

    assert await RoleFilter("admin")(message, user_repo, auth) is False


@pytest.mark.asyncio
async def test_missing_user_only_matches_guest_role_filter_even_with_staff_record():
    user_repo = FakeRoleUserRepository(None)
    auth = AuthService(FakeStaffRepository(Staff(telegram_user_id=10, clinic_id=1)))
    message = SimpleNamespace(from_user=SimpleNamespace(id=10))

    assert await RoleFilter(None)(message, user_repo, auth) is True
    assert await RoleFilter("admin")(message, user_repo, auth) is False
