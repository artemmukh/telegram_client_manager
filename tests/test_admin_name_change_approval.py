"""Handler-level tests for the admin-side name-change approval flow
(bot/handlers/admin/client_management/name_change_approval.py), including the
already-resolved (double-action) race guard."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.admin.client_management.name_change_approval import create_admin_name_change_router
from bot.keyboards.admin.name_change_cb import NameChangeApprovalCB
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.utils.role import Role

ADMIN_TELEGRAM_ID = 999
CLINIC_ID = 1


class FakeUserRepository:
    def __init__(self, user: User):
        self.user = user
        self.approved_ids = []
        self.rejected_ids = []
        self.already_resolved = False

    async def resolve_pending_full_name(self, user_id, approve: bool):
        if self.already_resolved:
            return None

        if approve:
            self.approved_ids.append(user_id)
            self.user.full_name = self.user.pending_full_name
        else:
            self.rejected_ids.append(user_id)

        self.user.pending_full_name = None
        return self.user

    async def get_user_by_id(self, user_id):
        return self.user

    async def get_client_by_id(self, user_id):
        return self.user if self.user.ID == user_id else None


class FakeStaffRepo:
    def __init__(self, staff):
        self.staff = staff

    async def get_staff(self, telegram_user_id):
        return self.staff


class FakeClinicRepo:
    def __init__(self, clinic):
        self.clinic = clinic

    async def get_clinic_by_id(self, clinic_id):
        return self.clinic


def _get_handler(observer, name):
    for handler in observer.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"Handler {name!r} not found")


@pytest.fixture
def client():
    return User(
        ID=7,
        full_name="Иван Иванов",
        pending_full_name="Петр Петров",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=555,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )


@pytest.fixture
def user_repo(client):
    return FakeUserRepository(client)


@pytest.fixture
def router(user_repo, client, fake_client_clinic_repo_factory):
    client_clinic_repo = fake_client_clinic_repo_factory(links={(client.ID, CLINIC_ID)})
    staff_repo = FakeStaffRepo(Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=CLINIC_ID, visibility_scope="clinic"))
    clinic_repo = FakeClinicRepo(Clinic(clinic_id=CLINIC_ID, name="Клиника Тест", token="t"))
    return create_admin_name_change_router(
        user_repo, staff_repo=staff_repo, clinic_repo=clinic_repo, client_clinic_repo=client_clinic_repo,
    )


def _admin_user():
    return User(
        ID=1, full_name="Админ Админов", phone="+998900000000", role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=CLINIC_ID,
    )


def _callback(user_id, action="approve"):
    callback = MagicMock()
    callback.from_user.id = ADMIN_TELEGRAM_ID
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.message.edit_reply_markup = AsyncMock()
    callback.bot = MagicMock()
    callback.bot.send_message = AsyncMock()
    return callback, NameChangeApprovalCB(action=action, user_id=user_id)


@pytest.mark.asyncio
async def test_approve_name_change_updates_name_and_notifies_client(router, user_repo, client):
    approve_name_change = _get_handler(router.callback_query, "approve_name_change")
    callback, callback_data = _callback(client.ID, action="approve")

    await approve_name_change(callback, callback_data, _admin_user())

    assert user_repo.approved_ids == [client.ID]
    callback.message.edit_text.assert_awaited_once()
    assert "Петр Петров" in callback.message.edit_text.call_args.args[0]

    callback.bot.send_message.assert_awaited_once()
    assert callback.bot.send_message.call_args.kwargs["chat_id"] == client.telegram_user_id


@pytest.mark.asyncio
async def test_reject_name_change_keeps_old_name_and_notifies_client(router, user_repo, client):
    reject_name_change = _get_handler(router.callback_query, "reject_name_change")
    callback, callback_data = _callback(client.ID, action="reject")

    await reject_name_change(callback, callback_data, _admin_user())

    assert user_repo.rejected_ids == [client.ID]
    assert client.full_name == "Иван Иванов"
    callback.message.edit_text.assert_awaited_once()
    callback.bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_approve_name_change_already_resolved_shows_alert(router, user_repo, client):
    user_repo.already_resolved = True
    approve_name_change = _get_handler(router.callback_query, "approve_name_change")
    callback, callback_data = _callback(client.ID, action="approve")

    await approve_name_change(callback, callback_data, _admin_user())

    callback.answer.assert_awaited_once()
    assert callback.answer.call_args.kwargs.get("show_alert") is True
    callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    callback.message.edit_text.assert_not_called()
    callback.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_reject_name_change_already_resolved_shows_alert(router, user_repo, client):
    user_repo.already_resolved = True
    reject_name_change = _get_handler(router.callback_query, "reject_name_change")
    callback, callback_data = _callback(client.ID, action="reject")

    await reject_name_change(callback, callback_data, _admin_user())

    callback.answer.assert_awaited_once()
    assert callback.answer.call_args.kwargs.get("show_alert") is True
    callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    callback.message.edit_text.assert_not_called()
    callback.bot.send_message.assert_not_called()

