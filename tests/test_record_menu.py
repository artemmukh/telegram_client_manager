"""Handler-level tests for record_menu.py's "back_to_main_records" callback,
plus command-wiring coverage for the two admin appointment routers that now
own the entrypoints record_managing used to funnel through.

Covers the "booking from a client's card" follow-up behaviour: when the
appointment-creation flow was entered via a client's card (client_preselected
in FSM data), cancelling/returning must land back on that client's card
(restoring search_data if the card was opened via search) instead of the
generic records menu. Also covers the just-added regression fix: if the
origin client was deleted in the meantime, render_client_card returns False
and back_to_main must fall back to editing the message into the generic
records menu rather than leaving it unedited.

Also covers command wiring: /appointments and /create_appointment used to
funnel into the record_managing choose-action menu; they now go straight to
their own flows (browse_appointments_message in appointment_browser.py,
start_create_message in appointment_creation.py) and no longer match
record_managing's filter.

Follows the direct-handler-call/fake-repository convention established in
test_appointment_creation_doctor_picker.py / test_appointment_creation_restart.py.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, User as TelegramUser

from bot.handlers.admin.appointment_management.appointment_browser import (
    create_admin_appointment_browser_router,
)
from bot.handlers.admin.appointment_management.appointment_creation import (
    create_admin_appointment_creation_router,
)
from bot.handlers.admin.appointment_management.record_menu import create_admin_record_router
from bot.handlers.utils.admin_utils.client_browser_helpers import build_client_card_text
from bot.keyboards.admin.client_management_kb.client_browser_kb import client_card_kb
from bot.keyboards.admin.record_management_kb.record_main_menu_kb import record_keyboard
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.states.admin.record_management.appointment_browser_states import AppointmentBrowserStates
from bot.states.admin.record_management.appointment_states import AppointmentCreationStates
from bot.utils.role import Role


ADMIN_TELEGRAM_ID = 999
CLINIC_ID = 1


def _admin_user():
    return User(full_name="Админ", phone="+998900000000", role=Role.ADMIN, telegram_user_id=ADMIN_TELEGRAM_ID, ID=1)


class FakeUserRepoForRecordMenu:
    def __init__(self, clients_by_id=None):
        self.clients_by_id = dict(clients_by_id or {})

    async def get_client_by_id(self, user_id):
        return self.clients_by_id.get(user_id)


class FakeStaffRepo:
    def __init__(self, staff=None):
        self.staff = staff or Staff(
            telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=CLINIC_ID, visibility_scope="clinic",
        )

    async def get_staff(self, telegram_user_id):
        return self.staff


class FakeClinicRepo:
    def __init__(self, clinic=None):
        self.clinic = clinic or Clinic(clinic_id=CLINIC_ID, name="Клиника Тест", token="t")

    async def get_clinic_by_id(self, clinic_id):
        return self.clinic


def _find_callback_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"callback handler {name} not found")


def _find_message_handler_object(router, name):
    for handler in router.message.handlers:
        if handler.callback.__name__ == name:
            return handler
    raise AssertionError(f"message handler {name} not found")


def _callback_query():
    callback_query = MagicMock()
    # ask_full_name/begin_appointment_creation (used by the new start_create/
    # start_create_message tests below) isinstance-branch on
    # CallbackQuery | Message; make this mock identify as a CallbackQuery so
    # it takes the edit_text branch instead of the Message/answer() one.
    callback_query.__class__ = CallbackQuery
    callback_query.from_user.id = ADMIN_TELEGRAM_ID
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _fsm_context():
    storage = MemoryStorage()
    key = (
        Chat(id=100, type="private").id,
        TelegramUser(id=ADMIN_TELEGRAM_ID, is_bot=False, first_name="Admin").id,
    )
    return FSMContext(storage=storage, key=key)


def _build_router(clients_by_id=None, client_clinic_repo=None):
    user_repo = FakeUserRepoForRecordMenu(clients_by_id=clients_by_id)
    return create_admin_record_router(
        user_repo, FakeStaffRepo(), FakeClinicRepo(), client_clinic_repo=client_clinic_repo,
    )


# --- record_managing (text-triggered entrypoint: legacy alias + button texts only) ---

@pytest.mark.asyncio
async def test_record_managing_filter_rejects_appointments_and_create_appointment_commands():
    """/appointments and /create_appointment no longer route through
    record_managing's choose-action menu -- they go straight to their own
    flows (browse_appointments_message in appointment_browser.py,
    start_create_message in appointment_creation.py). Only /record_managing
    and the two legacy button texts should still match this filter."""
    router = _build_router()
    handler = _find_message_handler_object(router, "record_managing")

    accepted_texts = ("/record_managing", "📒 Управление записями", "📅 Календарь")
    for text in accepted_texts:
        message = MagicMock()
        message.text = text
        matched, _ = await handler.check(message)
        assert matched is True, text

    rejected_texts = ("/appointments", "/create_appointment", "some other text")
    for text in rejected_texts:
        message = MagicMock()
        message.text = text
        matched, _ = await handler.check(message)
        assert matched is False, text


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger_text", ["/record_managing", "📒 Управление записями", "📅 Календарь"])
async def test_record_managing_still_answers_for_legacy_alias_and_button_text(trigger_text):
    """The commands/texts still left on this filter must keep showing the
    choose-action menu."""
    router = _build_router()
    record_managing = _find_message_handler_object(router, "record_managing").callback

    message = MagicMock()
    message.text = trigger_text
    message.answer = AsyncMock()

    await record_managing(message, _admin_user())

    message.answer.assert_awaited_once_with(
        text="Выберите действие над записью:", reply_markup=record_keyboard()
    )


# --- /appointments goes straight to browse_appointments_message (appointment_browser.py) ---

def _find_callback_handler_in(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"callback handler {name} not found")


def _find_message_handler_in(router, name):
    for handler in router.message.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"message handler {name} not found")


@pytest.mark.asyncio
async def test_browse_appointments_message_triggers_same_flow_as_callback():
    """/appointments (browse_appointments_message) must drive the exact same
    entry flow as the "🔍 Найти запись" callback (browse_appointments):
    same prompt/keyboard and same resulting FSM state."""
    router = create_admin_appointment_browser_router(
        "zb", MagicMock(), MagicMock(), MagicMock(), MagicMock(),
    )
    browse_appointments = _find_callback_handler_in(router, "browse_appointments")
    browse_appointments_message = _find_message_handler_in(router, "browse_appointments_message")

    callback_query = _callback_query()
    state_cb = _fsm_context()
    await browse_appointments(callback_query, state_cb, _admin_user())

    message = MagicMock()
    message.from_user.id = ADMIN_TELEGRAM_ID
    message.answer = AsyncMock(return_value=MagicMock())
    state_msg = _fsm_context()
    await browse_appointments_message(message, state_msg, _admin_user())

    callback_query.message.edit_text.assert_awaited_once()
    message.answer.assert_awaited_once()
    cb_args, cb_kwargs = callback_query.message.edit_text.await_args
    msg_args, msg_kwargs = message.answer.await_args
    assert cb_args[0] == msg_args[0]
    assert cb_kwargs["reply_markup"] == msg_kwargs["reply_markup"]

    assert await state_cb.get_state() == AppointmentBrowserStates.search_variant
    assert await state_msg.get_state() == AppointmentBrowserStates.search_variant


# --- /create_appointment goes straight to start_create_message (appointment_creation.py) ---

class FakeAppointmentRepoForCreation:
    async def create_appointment(self, appointment):
        return appointment


class FakeUserRepoForCreation:
    def __init__(self, admin=None, staff_by_clinic=None):
        self.admin = admin
        self.staff_by_clinic = staff_by_clinic or {}

    async def get_user_by_telegram_id(self, telegram_user_id):
        if self.admin and self.admin.telegram_user_id == telegram_user_id:
            return self.admin
        return None

    async def get_staff_users_by_clinic_id(self, clinic_id):
        return self.staff_by_clinic.get(clinic_id, [])


class FakeStaffRepoForCreation:
    def __init__(self, staff_by_telegram_id):
        self.staff_by_telegram_id = staff_by_telegram_id

    async def get_staff(self, telegram_user_id):
        return self.staff_by_telegram_id.get(telegram_user_id)

    async def get_staff_by_clinic_id(self, clinic_id):
        return [s for s in self.staff_by_telegram_id.values() if s.clinic_id == clinic_id]


class FakeClinicRepoForCreation:
    def __init__(self, clinic):
        self.clinic = clinic

    async def get_clinic_by_id(self, clinic_id):
        return self.clinic


@pytest.mark.asyncio
async def test_start_create_message_triggers_same_flow_as_callback():
    """/create_appointment (start_create_message) must drive the exact same
    begin_appointment_creation flow as the "➕ Создать запись" callback
    (start_create) -- here with doctors present, so both land on the
    doctor-picker state with an identical prompt/keyboard."""
    admin = User(
        full_name="Artem Upravlyayuschiy", phone="+998900000000", role=Role.ADMIN,
        telegram_user_id=ADMIN_TELEGRAM_ID, ID=42, clinic_id=CLINIC_ID, clinic_name="Zub Mudrosti",
    )
    doctor = User(
        full_name="Petrov Petr", phone="+998907654321", role=Role.ADMIN,
        telegram_user_id=1000, ID=99, clinic_id=CLINIC_ID, clinic_name="Zub Mudrosti",
    )
    user_repo = FakeUserRepoForCreation(admin=admin, staff_by_clinic={CLINIC_ID: [admin, doctor]})
    staff_repo = FakeStaffRepoForCreation({
        ADMIN_TELEGRAM_ID: Staff(telegram_user_id=ADMIN_TELEGRAM_ID, clinic_id=CLINIC_ID, visibility_scope="clinic"),
    })
    clinic_repo = FakeClinicRepoForCreation(Clinic(clinic_id=CLINIC_ID, name="Zub Mudrosti", token="t"))
    router = create_admin_appointment_creation_router(
        "zb", FakeAppointmentRepoForCreation(), user_repo, staff_repo, clinic_repo,
    )
    start_create = _find_callback_handler_in(router, "start_create")
    start_create_message = _find_message_handler_in(router, "start_create_message")

    callback_query = _callback_query()
    state_cb = _fsm_context()
    await start_create(callback_query, state_cb, admin)

    message = MagicMock()
    message.from_user.id = ADMIN_TELEGRAM_ID
    message.answer = AsyncMock()
    state_msg = _fsm_context()
    await start_create_message(message, state_msg, admin)

    assert await state_cb.get_state() == AppointmentCreationStates.choose_doctor
    assert await state_msg.get_state() == AppointmentCreationStates.choose_doctor
    assert await state_cb.get_data() == await state_msg.get_data()

    callback_query.message.edit_text.assert_awaited_once()
    message.answer.assert_awaited_once()
    cb_args, cb_kwargs = callback_query.message.edit_text.await_args
    msg_args, msg_kwargs = message.answer.await_args
    assert cb_args[0] == msg_args[0]
    assert cb_kwargs["reply_markup"] == msg_kwargs["reply_markup"]


# --- back_to_main with client_preselected: returns to the origin client's card ---

@pytest.mark.asyncio
async def test_back_to_main_with_client_preselected_renders_origin_card_and_restores_search_data(
    fake_client_clinic_repo_factory,
):
    client = User(ID=5, full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, clinic_id=1)
    client_clinic_repo = fake_client_clinic_repo_factory(links={(5, CLINIC_ID)})
    router = _build_router(clients_by_id={5: client}, client_clinic_repo=client_clinic_repo)
    back_to_main = _find_callback_handler(router, "back_to_main")

    state = _fsm_context()
    await state.update_data(
        client_preselected=True,
        full_name="Иванов Иван",
        phone="+998901234567",
        origin_client_id=5,
        origin_mode="search",
        origin_page=1,
        origin_search_data={"full_name": "Иванов"},
        staff_options={"42": "Врач"},
    )

    callback_query = _callback_query()
    await back_to_main(callback_query, state, _admin_user())

    data = await state.get_data()
    assert data.get("search_data") == {"full_name": "Иванов"}
    assert "client_preselected" not in data
    assert "origin_client_id" not in data
    assert "staff_options" not in data

    callback_query.answer.assert_awaited_once_with('')
    callback_query.message.edit_text.assert_awaited_once()
    args, kwargs = callback_query.message.edit_text.await_args
    assert args[0] == build_client_card_text(client)
    assert kwargs["reply_markup"] == client_card_kb(5, "search", 1)


@pytest.mark.asyncio
async def test_back_to_main_with_client_preselected_and_no_origin_search_data_does_not_set_search_data(
    fake_client_clinic_repo_factory,
):
    client = User(ID=5, full_name="Иванов Иван", phone="+998901234567", role=Role.CLIENT, clinic_id=1)
    client_clinic_repo = fake_client_clinic_repo_factory(links={(5, CLINIC_ID)})
    router = _build_router(clients_by_id={5: client}, client_clinic_repo=client_clinic_repo)
    back_to_main = _find_callback_handler(router, "back_to_main")

    state = _fsm_context()
    await state.update_data(
        client_preselected=True,
        full_name="Иванов Иван",
        phone="+998901234567",
        origin_client_id=5,
        origin_mode="list",
        origin_page=1,
    )

    callback_query = _callback_query()
    await back_to_main(callback_query, state, _admin_user())

    data = await state.get_data()
    assert "search_data" not in data
    callback_query.message.edit_text.assert_awaited_once()


# --- Regression: origin client deleted -> falls back to generic records menu ---

@pytest.mark.asyncio
async def test_back_to_main_falls_back_to_generic_menu_when_origin_client_deleted():
    router = _build_router(clients_by_id={})
    back_to_main = _find_callback_handler(router, "back_to_main")

    state = _fsm_context()
    await state.update_data(
        client_preselected=True,
        full_name="Иванов Иван",
        phone="+998901234567",
        origin_client_id=5,
        origin_mode="list",
        origin_page=1,
    )

    callback_query = _callback_query()
    await back_to_main(callback_query, state, _admin_user())

    callback_query.answer.assert_awaited_once_with("Клиент не найден.", show_alert=True)
    callback_query.message.edit_text.assert_awaited_once_with(
        "Выберите действие над записью:",
        reply_markup=record_keyboard(),
    )


# --- Regression check: client_preselected falsy/absent keeps original behaviour ---

@pytest.mark.asyncio
async def test_back_to_main_without_client_preselected_shows_generic_menu_unchanged():
    router = _build_router()
    back_to_main = _find_callback_handler(router, "back_to_main")

    state = _fsm_context()
    await state.update_data(some_unrelated_key="value")

    callback_query = _callback_query()
    await back_to_main(callback_query, state, _admin_user())

    data = await state.get_data()
    assert data == {}

    callback_query.answer.assert_awaited_once_with('')
    callback_query.message.edit_text.assert_awaited_once_with(
        "Выберите действие над записью:",
        reply_markup=record_keyboard(),
    )
