from __future__ import annotations

import pytest

from bot.exceptions.user_exceptions import PhoneAlreadyExistsError
from bot.models.user import User
from bot.models.user_settings import UserSettings


class FakeUserRepository:
    def __init__(
        self,
        existing_phones=None,
        existing_telegram_ids=None,
        clients_by_phone=None,
        clients_by_id=None,
        users_by_id=None,
        staff_by_clinic_id=None,
        clients_by_exact_name=None,
    ):
        self.existing_phones = set(existing_phones or [])
        self.existing_telegram_ids = set(existing_telegram_ids or [])
        self.clients_by_phone = dict(clients_by_phone or {})
        self.clients_by_id = dict(clients_by_id or {})
        self.clients_by_exact_name = dict(clients_by_exact_name or {})
        # get_user_by_id() is role-agnostic (clients AND admins), unlike
        # get_client_by_id(). Seed it from clients_by_id so existing tests
        # that only populate clients_by_id keep working, and allow callers
        # to additionally register non-client (e.g. admin) users here.
        self.users_by_id = dict(self.clients_by_id)
        self.users_by_id.update(users_by_id or {})
        self.staff_by_clinic_id = dict(staff_by_clinic_id or {})
        self.created_users: list[User] = []
        self.linked = []
        self.updated_clients = []
        self.deleted_clients: list[int] = []

    async def phone_exists(self, phone: str) -> bool:
        return phone in self.existing_phones

    async def user_exists(self, telegram_user_id: int) -> bool:
        return telegram_user_id in self.existing_telegram_ids

    async def create_user(self, user: User) -> None:
        if user.phone in self.existing_phones:
            raise PhoneAlreadyExistsError()

        self.created_users.append(user)
        self.existing_phones.add(user.phone)
        if user.telegram_user_id is not None:
            self.existing_telegram_ids.add(user.telegram_user_id)

    async def get_client_by_phone(self, phone):
        return self.clients_by_phone.get(phone)

    async def get_client_by_id(self, user_id):
        return self.clients_by_id.get(user_id)

    async def get_clients_by_exact_name(self, full_name, clinic_id):
        return self.clients_by_exact_name.get((full_name, clinic_id), [])

    async def get_user_by_id(self, user_id):
        return self.users_by_id.get(user_id)

    async def update_user_telegram_id(
        self, user_id, telegram_user_id, gender: str | None = None, birth_date: str | None = None,
    ):
        self.linked.append((user_id, telegram_user_id))
        user = self.users_by_id.get(user_id)
        if user is not None:
            user.telegram_user_id = telegram_user_id
            user.gender = gender
            user.birth_date = birth_date

    async def update_client(self, user_id, user):
        self.updated_clients.append((user_id, user))
        self.clients_by_id[user_id] = user
        self.users_by_id[user_id] = user
        return user

    async def get_staff_users_by_clinic_id(self, clinic_id):
        return self.staff_by_clinic_id.get(clinic_id, [])

    async def set_pending_full_name(self, user_id, new_full_name):
        user = self.users_by_id.get(user_id)
        if user is not None:
            user.pending_full_name = new_full_name

    async def resolve_pending_full_name(self, user_id, approve):
        user = self.users_by_id.get(user_id)
        if user is None or user.pending_full_name is None:
            return None

        if approve:
            user.full_name = user.pending_full_name

        user.pending_full_name = None
        return user

    async def delete_client(self, user_id) -> None:
        self.deleted_clients.append(user_id)
        self.clients_by_id.pop(user_id, None)
        self.users_by_id.pop(user_id, None)


@pytest.fixture
def fake_user_repo() -> FakeUserRepository:
    return FakeUserRepository()


@pytest.fixture
def fake_user_repo_factory():
    return FakeUserRepository


class FakeUserSettingsRepository:
    """Drop-in for UserSettingsRepository, matching its method names/signatures
    (init, upsert, get_by_user_id). Tracks every upsert() call in `updates`
    (mirroring the old FakeUserRepository.reminder_updates convention) so
    tests can assert exactly which (user_id, reminder_24h, reminder_2h) calls
    a service made, in addition to reading the resulting state back."""

    def __init__(self, settings_by_user_id=None):
        self.settings_by_user_id = dict(settings_by_user_id or {})
        self.updates: list[tuple[int, bool, bool]] = []

    async def init(self) -> None:
        pass

    async def upsert(self, user_id, reminder_24h, reminder_2h) -> None:
        self.updates.append((user_id, reminder_24h, reminder_2h))
        self.settings_by_user_id[user_id] = (reminder_24h, reminder_2h)

    async def get_by_user_id(self, user_id):
        settings = self.settings_by_user_id.get(user_id)
        if settings is None:
            return None
        reminder_24h, reminder_2h = settings
        return UserSettings(user_id=user_id, reminder_24h=reminder_24h, reminder_2h=reminder_2h)


@pytest.fixture
def fake_user_settings_repo() -> FakeUserSettingsRepository:
    return FakeUserSettingsRepository()


@pytest.fixture
def fake_user_settings_repo_factory():
    return FakeUserSettingsRepository


class FakeClinicRepository:
    def __init__(self, clinics_by_token=None):
        self.clinics_by_token = dict(clinics_by_token or {})

    async def get_clinic_by_token(self, token: str):
        return self.clinics_by_token.get(token)


@pytest.fixture
def fake_clinic_repo() -> FakeClinicRepository:
    return FakeClinicRepository()


class FakeClientClinicRepository:
    """Drop-in for ClientClinicRepository, matching its method names/signatures
    (link_client_to_clinic, client_linked_to_clinic, unlink_client_from_clinic,
    get_client_clinic_ids). Tracks (client_id, clinic_id) links in-memory and
    records unlink calls so tests can assert the exact rows that were touched."""

    def __init__(self, links=None):
        self.links = set(links or set())
        self.unlinked_calls: list[tuple[int, int]] = []

    async def link_client_to_clinic(self, client_id: int, clinic_id: int) -> None:
        self.links.add((client_id, clinic_id))

    async def client_linked_to_clinic(self, client_id: int, clinic_id: int) -> bool:
        return (client_id, clinic_id) in self.links

    async def unlink_client_from_clinic(self, client_id: int, clinic_id: int) -> None:
        self.unlinked_calls.append((client_id, clinic_id))
        self.links.discard((client_id, clinic_id))

    async def get_client_clinic_ids(self, client_id: int) -> list[int]:
        return [clinic_id for (cid, clinic_id) in self.links if cid == client_id]


@pytest.fixture
def fake_client_clinic_repo() -> FakeClientClinicRepository:
    return FakeClientClinicRepository()


@pytest.fixture
def fake_client_clinic_repo_factory():
    return FakeClientClinicRepository
