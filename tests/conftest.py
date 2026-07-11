from __future__ import annotations

import pytest

from bot.models.user import User


class FakeUserRepository:
    def __init__(
        self,
        existing_phones=None,
        existing_telegram_ids=None,
        clients_by_phone=None,
        clients_by_id=None,
        users_by_id=None,
        staff_by_clinic_id=None,
    ):
        self.existing_phones = set(existing_phones or [])
        self.existing_telegram_ids = set(existing_telegram_ids or [])
        self.clients_by_phone = dict(clients_by_phone or {})
        self.clients_by_id = dict(clients_by_id or {})
        # get_user_by_id() is role-agnostic (clients AND admins), unlike
        # get_client_by_id(). Seed it from clients_by_id so existing tests
        # that only populate clients_by_id keep working, and allow callers
        # to additionally register non-client (e.g. admin) users here.
        self.users_by_id = dict(self.clients_by_id)
        self.users_by_id.update(users_by_id or {})
        self.staff_by_clinic_id = dict(staff_by_clinic_id or {})
        self.created_users: list[User] = []
        self.linked = []
        self.reminder_updates = []
        self.updated_clients = []

    async def phone_exists(self, phone: str) -> bool:
        return phone in self.existing_phones

    async def user_exists(self, telegram_user_id: int) -> bool:
        return telegram_user_id in self.existing_telegram_ids

    async def create_user(self, user: User) -> None:
        self.created_users.append(user)
        self.existing_phones.add(user.phone)
        if user.telegram_user_id is not None:
            self.existing_telegram_ids.add(user.telegram_user_id)

    async def get_client_by_phone(self, phone):
        return self.clients_by_phone.get(phone)

    async def get_client_by_id(self, user_id):
        return self.clients_by_id.get(user_id)

    async def get_user_by_id(self, user_id):
        return self.users_by_id.get(user_id)

    async def update_user_telegram_id(self, user_id, telegram_user_id):
        self.linked.append((user_id, telegram_user_id))

    async def update_reminder_preferences(self, user_id, reminder_24h, reminder_2h):
        self.reminder_updates.append((user_id, reminder_24h, reminder_2h))

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


@pytest.fixture
def fake_user_repo() -> FakeUserRepository:
    return FakeUserRepository()


@pytest.fixture
def fake_user_repo_factory():
    return FakeUserRepository


class FakeClinicRepository:
    def __init__(self, clinics_by_token=None):
        self.clinics_by_token = dict(clinics_by_token or {})

    async def get_clinic_by_token(self, token: str):
        return self.clinics_by_token.get(token)


@pytest.fixture
def fake_clinic_repo() -> FakeClinicRepository:
    return FakeClinicRepository()
