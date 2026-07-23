from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, User as TelegramUser

from bot.exceptions.user_exceptions import UserNotFoundError
from bot.handlers.admin.client_management.client_browser import create_admin_client_browser_router
from bot.handlers.utils.admin_utils.appointment_helpers import DATETIME_INPUT_PROMPT
from bot.keyboards.admin.client_management_kb.client_browser_cb import (
    ClientActionCB,
    ClientCardCB,
    ClientPageCB,
)
from bot.keyboards.admin.client_management_kb.client_browser_kb import client_card_kb
from bot.keyboards.admin.record_management_kb.appointment_kb import back_to_records_kb
from bot.keyboards.client.booking_kb import booking_doctor_kb
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.repositories.client_clinic_repository import ClientClinicRepository
from bot.repositories.clinic_repository import ClinicRepository
from bot.repositories.user_repository import UserRepository
from bot.repositories.user_settings_repository import UserSettingsRepository
from bot.services.client.client_management import ClientManagement
from bot.services.client.client_pagination_service import ClientPaginationService
from bot.states.admin.record_management.appointment_states import AppointmentCreationStates
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
        await ClinicRepository(connection).init("zb")
        repo = UserRepository(connection)
        await repo.init()
        await UserSettingsRepository(connection).init()

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
        await ClinicRepository(connection).init("zb")
        user_repo = UserRepository(connection)
        client_clinic_repo = ClientClinicRepository(connection)
        await user_repo.init()
        await UserSettingsRepository(connection).init()
        await client_clinic_repo.init()

        clinic_id = 1
        first = User(full_name="Иванов Иван", phone="+998901111111", role=Role.CLIENT, clinic_id=clinic_id)
        await user_repo.create_user(first)
        await client_clinic_repo.link_client_to_clinic(first.ID, clinic_id)

        second = User(full_name="Иванов Пётр", phone="+998902222222", role=Role.CLIENT, clinic_id=clinic_id)
        await user_repo.create_user(second)
        await client_clinic_repo.link_client_to_clinic(second.ID, clinic_id)

        cl_mng = ClientManagement(
            user_repo, FakeStaffRepo(), FakeClinicRepo(), client_clinic_repository=client_clinic_repo,
        )
        pagination = ClientPaginationService(user_repo)

        # Search by name (fuzzy, multiple matches) - same mechanism the browser reuses.
        found = await cl_mng.search_client({"full_name": "Иванов"}, clinic_id)
        assert len(found) == 2

        # Pagination over the same search - what the list screen renders.
        result = await pagination.paginate_clients("search", 1, clinic_id, {"full_name": "Иванов"})
        assert result.total_count == 2
        assert len(result.items) == 2

        target_id = found[0].ID

        # Edit ФИО via the existing CRUD method - the card's "Изменить ФИО" action.
        updated = await cl_mng.update_client_name(target_id, "Иванов Иван-Обновлённый", clinic_id)
        assert updated.full_name == "Иванов Иван-Обновлённый"

        # Re-render the same page - updated name must be reflected.
        result = await pagination.paginate_clients("search", 1, clinic_id, {"full_name": "Иванов"})
        names = {u.ID: u.full_name for u in result.items}
        assert names[target_id] == "Иванов Иван-Обновлённый"

        # Delete - the card's "Удалить" action after confirmation.
        await cl_mng.delete_client(target_id, clinic_id)

        result = await pagination.paginate_clients("search", 1, clinic_id, {"full_name": "Иванов"})
        assert result.total_count == 1
        assert all(u.ID != target_id for u in result.items)

        with pytest.raises(UserNotFoundError):
            await cl_mng.search_client({"phone": "+998901111111"}, clinic_id)
    finally:
        await connection.close()


# --- Client search/list scoped to the acting admin's own clinic ---

@pytest.mark.asyncio
async def test_search_client_by_name_excludes_clients_from_other_clinics():
    connection = await aiosqlite.connect(":memory:")
    try:
        await ClinicRepository(connection).init("zb")
        user_repo = UserRepository(connection)
        client_clinic_repo = ClientClinicRepository(connection)
        await user_repo.init()
        await UserSettingsRepository(connection).init()
        await client_clinic_repo.init()

        client_in_clinic_1 = User(full_name="Иванов Иван", phone="+998901111111", role=Role.CLIENT, clinic_id=1)
        await user_repo.create_user(client_in_clinic_1)
        await client_clinic_repo.link_client_to_clinic(client_in_clinic_1.ID, 1)

        client_in_clinic_2 = User(full_name="Иванов Иван", phone="+998902222222", role=Role.CLIENT, clinic_id=2)
        await user_repo.create_user(client_in_clinic_2)
        await client_clinic_repo.link_client_to_clinic(client_in_clinic_2.ID, 2)

        cl_mng = ClientManagement(user_repo, FakeStaffRepo(), FakeClinicRepo())

        found = await cl_mng.search_client({"full_name": "Иванов"}, 1)

        assert [u.phone for u in found] == ["+998901111111"]

        with pytest.raises(UserNotFoundError):
            await cl_mng.search_client({"full_name": "Иванов"}, 3)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_search_client_by_phone_excludes_clients_from_other_clinics():
    connection = await aiosqlite.connect(":memory:")
    try:
        await ClinicRepository(connection).init("zb")
        user_repo = UserRepository(connection)
        client_clinic_repo = ClientClinicRepository(connection)
        await user_repo.init()
        await UserSettingsRepository(connection).init()
        await client_clinic_repo.init()

        client = User(full_name="Иванов Иван", phone="+998901111111", role=Role.CLIENT, clinic_id=1)
        await user_repo.create_user(client)
        await client_clinic_repo.link_client_to_clinic(client.ID, 1)

        cl_mng = ClientManagement(user_repo, FakeStaffRepo(), FakeClinicRepo())

        found = await cl_mng.search_client({"phone": "+998901111111"}, 1)
        assert [u.phone for u in found] == ["+998901111111"]

        with pytest.raises(UserNotFoundError):
            await cl_mng.search_client({"phone": "+998901111111"}, 2)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_paginate_clients_list_mode_excludes_other_clinics():
    connection = await aiosqlite.connect(":memory:")
    try:
        await ClinicRepository(connection).init("zb")
        user_repo = UserRepository(connection)
        client_clinic_repo = ClientClinicRepository(connection)
        await user_repo.init()
        await UserSettingsRepository(connection).init()
        await client_clinic_repo.init()

        client_in_clinic_1 = User(full_name="Иванов Иван", phone="+998901111111", role=Role.CLIENT, clinic_id=1)
        await user_repo.create_user(client_in_clinic_1)
        await client_clinic_repo.link_client_to_clinic(client_in_clinic_1.ID, 1)

        client_in_clinic_2 = User(full_name="Петров Петр", phone="+998902222222", role=Role.CLIENT, clinic_id=2)
        await user_repo.create_user(client_in_clinic_2)
        await client_clinic_repo.link_client_to_clinic(client_in_clinic_2.ID, 2)

        pagination = ClientPaginationService(user_repo)

        result = await pagination.paginate_clients("list", 1, 1)

        assert result.total_count == 1
        assert [u.phone for u in result.items] == ["+998901111111"]
    finally:
        await connection.close()


# --- client_card_kb: delete button removed ---

def test_client_card_kb_has_no_delete_button():
    markup = client_card_kb(client_id=1, mode="list", page=1)

    all_buttons = [button for row in markup.inline_keyboard for button in row]
    assert not any("delete" in (button.callback_data or "") for button in all_buttons)
    assert not any("Удалить" in button.text for button in all_buttons)


def test_client_card_kb_adjust_layout_has_three_rows_of_buttons():
    markup = client_card_kb(client_id=1, mode="list", page=1)

    row_lengths = [len(row) for row in markup.inline_keyboard]
    assert row_lengths == [2, 1, 1]


# --- start_delete: appointment-count warning ---

ADMIN_TELEGRAM_ID = 999


class FakeUserRepoForDelete:
    def __init__(self, client):
        self.client = client

    async def get_client_by_id(self, user_id):
        return self.client if self.client and self.client.ID == user_id else None


class FakeAppointmentRepoForDelete:
    def __init__(self, count):
        self.count = count

    async def count_appointments_by_client_id(self, client_id, clinic_id):
        return self.count


class FakeStaffRepoForDelete:
    def __init__(self, staff):
        self.staff = staff

    async def get_staff(self, telegram_user_id):
        return self.staff


class FakeClinicRepoForDelete:
    def __init__(self, clinic):
        self.clinic = clinic

    async def get_clinic_by_id(self, clinic_id):
        return self.clinic


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _callback_query():
    callback_query = MagicMock()
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


async def _run_start_delete(appointments_count, client_clinic_repo_factory):
    client = User(ID=1, full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, clinic_id=1)
    user_repo = FakeUserRepoForDelete(client)
    appointment_repo = FakeAppointmentRepoForDelete(appointments_count)
    staff_repo = FakeStaffRepoForDelete(
        Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="clinic"),
    )
    clinic_repo = FakeClinicRepoForDelete(Clinic(clinic_id=1, name="Клиника Тест", token="t"))
    client_clinic_repo = client_clinic_repo_factory(links={(client.ID, 1)})
    router = create_admin_client_browser_router(
        user_repo, staff_repo, clinic_repo, appointment_repo, client_clinic_repo,
    )
    start_delete = _find_handler(router, "start_delete")

    callback_data = ClientActionCB(action="delete", client_id=1, mode="list", page=1)
    callback_query = _callback_query()
    await start_delete(callback_query, callback_data, AsyncMock())

    return callback_query.message.edit_text.call_args.args[0]


@pytest.mark.asyncio
async def test_start_delete_warning_omits_count_when_no_appointments(fake_client_clinic_repo_factory):
    text = await _run_start_delete(0, fake_client_clinic_repo_factory)

    assert "записи на приём" not in text


@pytest.mark.asyncio
async def test_start_delete_warning_includes_count_when_appointments_exist(fake_client_clinic_repo_factory):
    text = await _run_start_delete(3, fake_client_clinic_repo_factory)

    assert "записи на приём" in text
    assert "3" in text


# --- new_appointment: book directly from a client's card, skipping FIO/phone entry ---

class FakeUserRepoForNewAppointment:
    def __init__(self, clients_by_id=None, staff_by_clinic=None):
        self.clients_by_id = dict(clients_by_id or {})
        self.staff_by_clinic = staff_by_clinic or {}

    async def get_client_by_id(self, user_id):
        return self.clients_by_id.get(user_id)

    async def get_staff_users_by_clinic_id(self, clinic_id):
        return self.staff_by_clinic.get(clinic_id, [])


class FakeStaffRepoForNewAppointment:
    def __init__(self, staff_by_telegram_id):
        self.staff_by_telegram_id = staff_by_telegram_id

    async def get_staff(self, telegram_user_id):
        return self.staff_by_telegram_id.get(telegram_user_id)

    async def get_staff_by_clinic_id(self, clinic_id):
        return [s for s in self.staff_by_telegram_id.values() if s.clinic_id == clinic_id]


class FakeClinicRepoForNewAppointment:
    def __init__(self, clinic):
        self.clinic = clinic

    async def get_clinic_by_id(self, clinic_id):
        return self.clinic


def _new_appointment_client():
    return User(ID=5, full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, clinic_id=1)


def _new_appointment_fsm_context():
    storage = MemoryStorage()
    key = (
        Chat(id=100, type="private").id,
        TelegramUser(id=ADMIN_TELEGRAM_ID, is_bot=False, first_name="Admin").id,
    )
    return FSMContext(storage=storage, key=key)


def _build_new_appointment_router(client, staff_by_telegram_id, staff_by_clinic=None, client_clinic_repo=None):
    user_repo = FakeUserRepoForNewAppointment(
        clients_by_id={client.ID: client} if client else {},
        staff_by_clinic=staff_by_clinic or {},
    )
    staff_repo = FakeStaffRepoForNewAppointment(staff_by_telegram_id)
    clinic_repo = FakeClinicRepoForNewAppointment(Clinic(clinic_id=1, name="Клиника Тест", token="t"))
    return create_admin_client_browser_router(
        user_repo, staff_repo, clinic_repo, client_clinic_repo=client_clinic_repo,
    )


@pytest.mark.asyncio
async def test_new_appointment_own_scope_admin_goes_straight_to_datetime_with_preselect_and_origin_data(
    fake_client_clinic_repo_factory,
):
    client = _new_appointment_client()
    staff_by_telegram_id = {
        ADMIN_TELEGRAM_ID: Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="own"),
    }
    client_clinic_repo = fake_client_clinic_repo_factory(links={(client.ID, 1)})
    router = _build_new_appointment_router(client, staff_by_telegram_id, client_clinic_repo=client_clinic_repo)
    new_appointment = _find_handler(router, "new_appointment")

    callback_data = ClientActionCB(action="new_appointment", client_id=5, mode="list", page=2)
    callback_query = _callback_query()
    state = _new_appointment_fsm_context()

    await new_appointment(callback_query, callback_data, state)

    assert await state.get_state() == AppointmentCreationStates.appointment_datetime
    data = await state.get_data()
    assert data["client_preselected"] is True
    assert data["full_name"] == client.full_name
    assert data["phone"] == client.phone
    assert data["origin_client_id"] == 5
    assert data["origin_mode"] == "list"
    assert data["origin_page"] == 2
    assert "origin_search_data" not in data

    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == DATETIME_INPUT_PROMPT
    assert kwargs["reply_markup"] == back_to_records_kb()


@pytest.mark.asyncio
async def test_new_appointment_clinic_wide_admin_shows_doctor_picker_with_preselect_and_origin_data(
    fake_client_clinic_repo_factory,
):
    client = _new_appointment_client()
    admin = User(
        ID=42, full_name="Управляющий", phone="+998900000000", role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1,
    )
    doctor = User(
        ID=99, full_name="Петров Петр", phone="+998907654321", role=Role.ADMIN,
        telegram_user_id=1000, clinic_id=1,
    )
    staff_by_telegram_id = {
        ADMIN_TELEGRAM_ID: Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="clinic"),
        1000: Staff(telegram_user_id=1000, clinic_id=1, visibility_scope="own"),
    }
    client_clinic_repo = fake_client_clinic_repo_factory(links={(client.ID, 1)})
    router = _build_new_appointment_router(
        client, staff_by_telegram_id, staff_by_clinic={1: [admin, doctor]}, client_clinic_repo=client_clinic_repo,
    )
    new_appointment = _find_handler(router, "new_appointment")

    callback_data = ClientActionCB(action="new_appointment", client_id=5, mode="search", page=1)
    callback_query = _callback_query()
    state = _new_appointment_fsm_context()

    await new_appointment(callback_query, callback_data, state)

    assert await state.get_state() == AppointmentCreationStates.choose_doctor
    data = await state.get_data()
    assert data["client_preselected"] is True
    assert data["full_name"] == client.full_name
    assert data["phone"] == client.phone
    assert data["origin_client_id"] == 5
    assert data["origin_mode"] == "search"
    assert data["origin_page"] == 1
    assert data["staff_options"] == {"42": "Управляющий", "99": "Петров Петр"}

    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == "Выберите врача:"
    assert kwargs["reply_markup"] == booking_doctor_kb([admin, doctor], cancel_callback_data="back_to_main_records")


@pytest.mark.asyncio
async def test_new_appointment_from_search_result_threads_search_data_into_origin_search_data(
    fake_client_clinic_repo_factory,
):
    client = _new_appointment_client()
    staff_by_telegram_id = {
        ADMIN_TELEGRAM_ID: Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="own"),
    }
    client_clinic_repo = fake_client_clinic_repo_factory(links={(client.ID, 1)})
    router = _build_new_appointment_router(client, staff_by_telegram_id, client_clinic_repo=client_clinic_repo)
    new_appointment = _find_handler(router, "new_appointment")

    callback_data = ClientActionCB(action="new_appointment", client_id=5, mode="search", page=1)
    callback_query = _callback_query()
    state = _new_appointment_fsm_context()
    await state.update_data(search_data={"full_name": "Иванов"})

    await new_appointment(callback_query, callback_data, state)

    data = await state.get_data()
    assert data["origin_search_data"] == {"full_name": "Иванов"}
    assert data["client_preselected"] is True
    assert await state.get_state() == AppointmentCreationStates.appointment_datetime


@pytest.mark.asyncio
async def test_new_appointment_client_not_found_shows_alert_and_does_not_touch_fsm():
    staff_by_telegram_id = {
        ADMIN_TELEGRAM_ID: Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="own"),
    }
    router = _build_new_appointment_router(None, staff_by_telegram_id)
    new_appointment = _find_handler(router, "new_appointment")

    callback_data = ClientActionCB(action="new_appointment", client_id=5, mode="list", page=1)
    callback_query = _callback_query()
    state = _new_appointment_fsm_context()

    await new_appointment(callback_query, callback_data, state)

    callback_query.answer.assert_awaited_once_with("Клиент не найден.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    assert await state.get_state() is None
    assert await state.get_data() == {}
