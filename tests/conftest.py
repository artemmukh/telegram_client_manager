from __future__ import annotations

import pytest

from bot.models.user import User


class FakeUserRepository:
    def __init__(self, existing_phones=None, existing_telegram_ids=None, clients_by_phone=None):
        self.existing_phones = set(existing_phones or [])
        self.existing_telegram_ids = set(existing_telegram_ids or [])
        self.clients_by_phone = dict(clients_by_phone or {})
        self.created_users: list[User] = []
        self.linked = []

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

    async def update_user_telegram_id(self, user_id, telegram_user_id):
        self.linked.append((user_id, telegram_user_id))


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
