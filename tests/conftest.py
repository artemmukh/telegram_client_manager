from __future__ import annotations

import pytest

from bot.models.user import User


class FakeUserRepository:
    def __init__(self, existing_phones=None, existing_telegram_ids=None):
        self.existing_phones = set(existing_phones or [])
        self.existing_telegram_ids = set(existing_telegram_ids or [])
        self.created_users: list[User] = []

    async def phone_exists(self, phone: str) -> bool:
        return phone in self.existing_phones

    async def user_exists(self, telegram_user_id: int) -> bool:
        return telegram_user_id in self.existing_telegram_ids

    async def create_user(self, user: User) -> None:
        self.created_users.append(user)
        self.existing_phones.add(user.phone)
        if user.telegram_user_id is not None:
            self.existing_telegram_ids.add(user.telegram_user_id)


@pytest.fixture
def fake_user_repo() -> FakeUserRepository:
    return FakeUserRepository()


@pytest.fixture
def fake_user_repo_factory():
    return FakeUserRepository
