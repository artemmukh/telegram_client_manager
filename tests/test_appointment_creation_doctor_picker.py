"""Handler-level tests for the doctor-selection step of admin appointment
creation (appointment_creation.py).

The service-level behaviour of list_clinic_doctors_for_creation and
create_appointment's staff_user_id resolution is already covered in
test_appointment_management.py. This file checks the handler wiring on top
of it: does start_create branch into the choose_doctor state and render the
picker keyboard, does own/None scope skip it entirely, and does pick_doctor
correctly consume ClientBookDoctorCB and hand off to ask_full_name.

Follows the direct-handler-call convention used elsewhere in this admin
appointment area (see test_appointment_browser_ownership.py,
test_appointment_browser_propose_handler.py): build the router with fake
repositories, pull the decorated callback out of router.callback_query
handlers, and invoke it directly with mock aiogram objects.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.admin.appointment_management.appointment_creation import (
    create_admin_appointment_creation_router,
)
from bot.handlers.utils.admin_utils.appointment_helpers import DATETIME_INPUT_PROMPT
from bot.keyboards.admin.record_management_kb.appointment_kb import back_to_records_kb
from bot.keyboards.client.booking_cb import ClientBookDoctorCB
from bot.keyboards.client.booking_kb import booking_doctor_kb
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.states.admin.record_management.appointment_states import AppointmentCreationStates
from bot.utils.role import Role


ADMIN_TELEGRAM_ID = 999


class FakeAppointmentRepository:
    async def create_appointment(self, appointment):
        return appointment


class FakeUserRepo:
    def __init__(self, admin=None, staff_by_clinic=None):
        self.admin = admin
        self.staff_by_clinic = staff_by_clinic or {}

    async def get_user_by_telegram_id(self, telegram_user_id):
        if self.admin and self.admin.telegram_user_id == telegram_user_id:
            return self.admin
        return None

    async def get_staff_users_by_clinic_id(self, clinic_id):
        return self.staff_by_clinic.get(clinic_id, [])


class FakeStaffRepo:
    def __init__(self, staff_by_telegram_id):
        self.staff_by_telegram_id = staff_by_telegram_id

    async def get_staff(self, telegram_user_id):
        return self.staff_by_telegram_id.get(telegram_user_id)

    async def get_staff_by_clinic_id(self, clinic_id):
        return [s for s in self.staff_by_telegram_id.values() if s.clinic_id == clinic_id]


class FakeClinicRepo:
    def __init__(self, clinic):
        self.clinic = clinic

    async def get_clinic_by_id(self, clinic_id):
        return self.clinic


def _admin(staff_id=42, telegram_user_id=ADMIN_TELEGRAM_ID, full_name="Artem Upravlyayuschiy"):
    return User(
        full_name=full_name,
        phone="+998900000000",
        role=Role.ADMIN,
        telegram_user_id=telegram_user_id,
        ID=staff_id,
        clinic_id=1,
        clinic_name="Zub Mudrosti",
    )


def _doctor(staff_id, telegram_user_id, full_name="Petrov Petr"):
    return User(
        full_name=full_name,
        phone="+998907654321",
        role=Role.ADMIN,
        telegram_user_id=telegram_user_id,
        ID=staff_id,
        clinic_id=1,
        clinic_name="Zub Mudrosti",
    )


def _build_router(user_repo, staff_repo):
    clinic_repo = FakeClinicRepo(Clinic(clinic_id=1, name="Zub Mudrosti", token="t"))
    return create_admin_appointment_creation_router(
        "zb", FakeAppointmentRepository(), user_repo, staff_repo, clinic_repo,
    )


def _find_callback_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"callback handler {name} not found")


def _callback_query(telegram_user_id=ADMIN_TELEGRAM_ID):
    callback_query = MagicMock()
    callback_query.from_user.id = telegram_user_id
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _state(**data):
    state = MagicMock()
    state.get_data = AsyncMock(return_value=data)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


# --- start_create: clinic scope shows the picker ---

@pytest.mark.asyncio
async def test_start_create_with_clinic_scope_shows_doctor_picker_and_sets_state():
    admin = _admin()
    doctor = _doctor(99, 1000)
    user_repo = FakeUserRepo(admin=admin, staff_by_clinic={1: [admin, doctor]})
    staff_repo = FakeStaffRepo({
        ADMIN_TELEGRAM_ID: Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="clinic"),
        1000: Staff(telegram_user_id=1000, clinic_id=1, visibility_scope="own"),
    })
    router = _build_router(user_repo, staff_repo)
    start_create = _find_callback_handler(router, "start_create")

    callback_query = _callback_query()
    state = _state()

    await start_create(callback_query, state)

    state.set_state.assert_awaited_once_with(AppointmentCreationStates.choose_doctor)

    update_calls = [call.kwargs for call in state.update_data.await_args_list]
    assert {"staff_options": {"42": "Artem Upravlyayuschiy", "99": "Petrov Petr"}} in update_calls

    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    expected_markup = booking_doctor_kb([admin, doctor], cancel_callback_data="back_to_main_records")
    assert kwargs["reply_markup"] == expected_markup


# --- start_create: own/None scope skips the picker entirely ---

@pytest.mark.asyncio
async def test_start_create_with_own_scope_skips_picker_goes_straight_to_full_name():
    admin = _admin()
    user_repo = FakeUserRepo(admin=admin, staff_by_clinic={1: [admin]})
    staff_repo = FakeStaffRepo({
        ADMIN_TELEGRAM_ID: Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="own"),
    })
    router = _build_router(user_repo, staff_repo)
    start_create = _find_callback_handler(router, "start_create")

    callback_query = _callback_query()
    state = _state()

    await start_create(callback_query, state)

    state.set_state.assert_awaited_once_with(AppointmentCreationStates.client_full_name)

    update_calls = [call.kwargs for call in state.update_data.await_args_list]
    assert not any("staff_options" in kwargs for kwargs in update_calls)

    callback_query.message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_create_with_none_scope_skips_picker_goes_straight_to_full_name():
    admin = _admin()
    user_repo = FakeUserRepo(admin=admin, staff_by_clinic={1: [admin]})
    staff_repo = FakeStaffRepo({
        ADMIN_TELEGRAM_ID: Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope=None),
    })
    router = _build_router(user_repo, staff_repo)
    start_create = _find_callback_handler(router, "start_create")

    callback_query = _callback_query()
    state = _state()

    await start_create(callback_query, state)

    state.set_state.assert_awaited_once_with(AppointmentCreationStates.client_full_name)
    callback_query.message.edit_text.assert_awaited_once()


# --- pick_doctor ---

@pytest.mark.asyncio
async def test_pick_doctor_stores_staff_user_id_and_name_transitions_to_full_name():
    admin = _admin()
    user_repo = FakeUserRepo(admin=admin)
    staff_repo = FakeStaffRepo({
        ADMIN_TELEGRAM_ID: Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="clinic"),
    })
    router = _build_router(user_repo, staff_repo)
    pick_doctor = _find_callback_handler(router, "pick_doctor")

    callback_query = _callback_query()
    state = _state(staff_options={"99": "Petrov Petr"})
    callback_data = ClientBookDoctorCB(staff_user_id=99)

    await pick_doctor(callback_query, callback_data, state)

    state.update_data.assert_awaited_once_with(staff_user_id=99, staff_name="Petrov Petr")
    state.set_state.assert_awaited_once_with(AppointmentCreationStates.client_full_name)
    callback_query.message.edit_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_pick_doctor_falls_back_to_generic_label_when_id_not_in_options():
    admin = _admin()
    user_repo = FakeUserRepo(admin=admin)
    staff_repo = FakeStaffRepo({
        ADMIN_TELEGRAM_ID: Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="clinic"),
    })
    router = _build_router(user_repo, staff_repo)
    pick_doctor = _find_callback_handler(router, "pick_doctor")

    callback_query = _callback_query()
    state = _state(staff_options={"99": "Petrov Petr"})
    callback_data = ClientBookDoctorCB(staff_user_id=404)

    await pick_doctor(callback_query, callback_data, state)

    state.update_data.assert_awaited_once_with(staff_user_id=404, staff_name="Врач")
    state.set_state.assert_awaited_once_with(AppointmentCreationStates.client_full_name)


# --- pick_doctor: client_preselected (booking from a client's card) skips FIO entry ---

@pytest.mark.asyncio
async def test_pick_doctor_with_client_preselected_skips_full_name_goes_straight_to_datetime():
    admin = _admin()
    user_repo = FakeUserRepo(admin=admin)
    staff_repo = FakeStaffRepo({
        ADMIN_TELEGRAM_ID: Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=1, visibility_scope="clinic"),
    })
    router = _build_router(user_repo, staff_repo)
    pick_doctor = _find_callback_handler(router, "pick_doctor")

    callback_query = _callback_query()
    state = _state(
        staff_options={"99": "Petrov Petr"},
        client_preselected=True,
        full_name="Иванов Иван",
        phone="+998901234567",
        origin_client_id=5,
        origin_mode="list",
        origin_page=1,
    )
    callback_data = ClientBookDoctorCB(staff_user_id=99)

    await pick_doctor(callback_query, callback_data, state)

    state.update_data.assert_awaited_once_with(staff_user_id=99, staff_name="Petrov Petr")
    state.set_state.assert_awaited_once_with(AppointmentCreationStates.appointment_datetime)
    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == DATETIME_INPUT_PROMPT
    assert kwargs["reply_markup"] == back_to_records_kb()
