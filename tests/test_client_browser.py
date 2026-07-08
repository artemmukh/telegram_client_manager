import aiosqlite
import pytest

from bot.exceptions.user_exceptions import UserNotFoundError
from bot.keyboards.admin.client_management_kb.client_browser_cb import (
    ClientActionCB,
    ClientCardCB,
    ClientPageCB,
)
from bot.models.user import User
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.user_repository import UserRepository
from bot.services.client.client_management import ClientManagement
from bot.services.client.client_pagination_service import ClientPaginationService
from bot.utils.role import Role
from bot.utils.tools import format_phone_short


# --- format_phone_short ---

@pytest.mark.parametrize(
    "phone, expected",
    [
        ("+998901234567", "90 123-45-67"),
        ("998901234567", "90 123-45-67"),
        ("901234567", "90 123-45-67"),
        ("+998331743788", "33 174-37-88"),
    ],
)
def test_format_phone_short_formats_uzbek_numbers(phone, expected):
    assert format_phone_short(phone) == expected


def test_format_phone_short_falls_back_on_unexpected_format():
    assert format_phone_short("+1234567") == "+1234567"


# --- CallbackData factories ---

def test_client_page_cb_round_trip():
    packed = ClientPageCB(mode="search", page=3).pack()
    assert len(packed.encode("utf-8")) <= 64

    unpacked = ClientPageCB.unpack(packed)
    assert unpacked.mode == "search"
    assert unpacked.page == 3


def test_client_card_cb_round_trip():
    packed = ClientCardCB(client_id=123456, mode="list", page=7).pack()
    assert len(packed.encode("utf-8")) <= 64

    unpacked = ClientCardCB.unpack(packed)
    assert unpacked.client_id == 123456
    assert unpacked.mode == "list"
    assert unpacked.page == 7


def test_client_action_cb_round_trip_with_longest_action_name():
    # "confirm_delete" is the longest action string used - worst case for the 64-byte budget.
    packed = ClientActionCB(action="confirm_delete", client_id=999999, mode="search", page=9999).pack()
    assert len(packed.encode("utf-8")) <= 64

    unpacked = ClientActionCB.unpack(packed)
    assert unpacked.action == "confirm_delete"
    assert unpacked.client_id == 999999
    assert unpacked.mode == "search"
    assert unpacked.page == 9999


# --- UserRepository ORDER BY determinism ---

@pytest.mark.asyncio
async def test_get_clients_page_orders_deterministically_for_same_full_name():
    connection = await aiosqlite.connect(":memory:")
    try:
        await ClinicRepository(connection).init()
        repo = UserRepository(connection)
        await repo.init()

        same_name = "Артем Артем"
        first = User(full_name=same_name, phone="+998900000001", role=Role.CLIENT)
        second = User(full_name=same_name, phone="+998900000002", role=Role.CLIENT)
        await repo.create_user(first)
        await repo.create_user(second)

        page = await repo.get_clients_page(1, per_page=10)

        assert [u.phone for u in page] == ["+998900000001", "+998900000002"]
    finally:
        await connection.close()


# --- Reused business logic composes correctly for the browser flow ---

class FakeStaffRepo:
    pass


class FakeClinicRepo:
    pass


@pytest.mark.asyncio
async def test_search_paginate_update_delete_flow_composes():
    connection = await aiosqlite.connect(":memory:")
    try:
        await ClinicRepository(connection).init()
        user_repo = UserRepository(connection)
        await user_repo.init()

        await user_repo.create_user(
            User(full_name="Иванов Иван", phone="+998901111111", role=Role.CLIENT)
        )
        await user_repo.create_user(
            User(full_name="Иванов Пётр", phone="+998902222222", role=Role.CLIENT)
        )

        cl_mng = ClientManagement(user_repo, FakeStaffRepo(), FakeClinicRepo())
        pagination = ClientPaginationService(user_repo)

        # Search by name (fuzzy, multiple matches) - same mechanism the browser reuses.
        found = await cl_mng.search_client({"full_name": "Иванов"})
        assert len(found) == 2

        # Pagination over the same search - what the list screen renders.
        result = await pagination.paginate_clients("search", 1, {"full_name": "Иванов"})
        assert result.total_count == 2
        assert len(result.items) == 2

        target_id = found[0].ID

        # Edit ФИО via the existing CRUD method - the card's "Изменить ФИО" action.
        updated = await cl_mng.update_client_name(target_id, "Иванов Иван-Обновлённый")
        assert updated.full_name == "Иванов Иван-Обновлённый"

        # Re-render the same page - updated name must be reflected.
        result = await pagination.paginate_clients("search", 1, {"full_name": "Иванов"})
        names = {u.ID: u.full_name for u in result.items}
        assert names[target_id] == "Иванов Иван-Обновлённый"

        # Delete - the card's "Удалить" action after confirmation.
        await cl_mng.delete_client(target_id)

        result = await pagination.paginate_clients("search", 1, {"full_name": "Иванов"})
        assert result.total_count == 1
        assert all(u.ID != target_id for u in result.items)

        with pytest.raises(UserNotFoundError):
            await cl_mng.search_client({"phone": "+998901111111"})
    finally:
        await connection.close()
