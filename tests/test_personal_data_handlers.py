"""Handler-level tests for the profile "add birth date and gender" flow
(bot/handlers/common/personal_data.py). Covers the direct-DB-write flow
(no admin approval, unlike name-change) and the retry-trap fix: a
format-valid but business-invalid birth date (future date / age>120) only
fails inside client_management_service.update_personal_data, one step after
the birth-date prompt, so choose_gender must reset the user back to the
birth_date state on failure instead of leaving them stuck re-tapping the
same gender buttons."""

from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from bot.exceptions.user_exceptions import InvalidBirthDateError
from bot.handlers.common.personal_data import create_personal_data_router
from bot.keyboards.utils.gender_cb import GenderCB
from bot.models.user import User
from bot.states.profile_personal_data_states import ProfilePersonalDataStates
from bot.utils.role import Role


class FakeClientManagement:
    """Mirrors ClientManagement.update_personal_data's real contract: the
    raw DD.MM.YYYY birth_date received from the FSM is normalized to
    YYYY-MM-DD before being stored on the returned User (build_profile_text
    expects the ISO form and reformats it for display)."""

    def __init__(self, user: User, raise_error: Exception | None = None):
        self.user = user
        self.raise_error = raise_error
        self.calls = []

    async def update_personal_data(self, user_id, *, birth_date, gender):
        self.calls.append((user_id, birth_date, gender))
        if self.raise_error is not None:
            raise self.raise_error
        self.user.birth_date = datetime.strptime(birth_date, "%d.%m.%Y").strftime("%Y-%m-%d")
        self.user.gender = gender
        return self.user


def _get_handler(observer, name):
    for handler in observer.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"Handler {name!r} not found")


def _client_user():
    return User(
        ID=7,
        full_name="Иван Иванов",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=555,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )


def _admin_user():
    return User(
        ID=9,
        full_name="Админ Админов",
        phone="+998907654321",
        role=Role.ADMIN,
        telegram_user_id=777,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )


@pytest.fixture
def fsm_context():
    return FSMContext(storage=MemoryStorage(), key=(1, 1))


def _callback(data="profile_personal_data"):
    callback = MagicMock()
    callback.data = data
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    return callback


def _message(text):
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    return message


def _router(client_management):
    return create_personal_data_router(client_management)


@pytest.mark.asyncio
async def test_open_personal_data_clears_state_and_shows_submenu(fsm_context):
    current_user = _client_user()
    router = _router(FakeClientManagement(current_user))
    open_personal_data = _get_handler(router.callback_query, "open_personal_data")

    await fsm_context.set_state(ProfilePersonalDataStates.gender)
    await fsm_context.update_data(birth_date="05.03.1990")

    await open_personal_data(_callback(), fsm_context, current_user=current_user)

    assert await fsm_context.get_state() is None
    assert await fsm_context.get_data() == {}


@pytest.mark.asyncio
async def test_start_add_birth_date_sets_birth_date_state(fsm_context):
    router = _router(FakeClientManagement(_client_user()))
    start_add_birth_date = _get_handler(router.callback_query, "start_add_birth_date")

    await start_add_birth_date(_callback(data="profile_add_birth_date"), fsm_context)

    assert await fsm_context.get_state() == ProfilePersonalDataStates.birth_date


@pytest.mark.asyncio
async def test_process_birth_date_invalid_format_stays_in_birth_date_state(fsm_context):
    router = _router(FakeClientManagement(_client_user()))
    process_birth_date = _get_handler(router.message, "process_birth_date")

    await fsm_context.set_state(ProfilePersonalDataStates.birth_date)
    message = _message("not-a-date")

    await process_birth_date(message, fsm_context)

    assert await fsm_context.get_state() == ProfilePersonalDataStates.birth_date
    message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_birth_date_valid_format_transitions_to_gender_state(fsm_context):
    router = _router(FakeClientManagement(_client_user()))
    process_birth_date = _get_handler(router.message, "process_birth_date")

    await fsm_context.set_state(ProfilePersonalDataStates.birth_date)
    message = _message("05.03.1990")

    await process_birth_date(message, fsm_context)

    assert await fsm_context.get_state() == ProfilePersonalDataStates.gender
    data = await fsm_context.get_data()
    assert data["birth_date"] == "05.03.1990"
    message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_choose_gender_success_persists_and_returns_to_top_level_profile(fsm_context):
    current_user = _client_user()
    client_management = FakeClientManagement(current_user)
    router = _router(client_management)
    choose_gender = _get_handler(router.callback_query, "choose_gender")

    await fsm_context.set_state(ProfilePersonalDataStates.gender)
    await fsm_context.update_data(birth_date="05.03.1990")

    callback = _callback(data="reg_gender:male")
    await choose_gender(callback, GenderCB(value="male"), fsm_context, current_user=current_user)

    assert client_management.calls == [(current_user.ID, "05.03.1990", "male")]
    assert await fsm_context.get_state() is None
    callback.answer.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()
    args, kwargs = callback.message.edit_text.call_args
    assert "Иван Иванов" in args[0]


@pytest.mark.asyncio
async def test_choose_gender_works_for_admin_user(fsm_context):
    admin_user = _admin_user()
    client_management = FakeClientManagement(admin_user)
    router = _router(client_management)
    choose_gender = _get_handler(router.callback_query, "choose_gender")

    await fsm_context.set_state(ProfilePersonalDataStates.gender)
    await fsm_context.update_data(birth_date="12.11.1985")

    await choose_gender(
        _callback(data="reg_gender:female"), GenderCB(value="female"), fsm_context, current_user=admin_user,
    )

    assert client_management.calls == [(admin_user.ID, "12.11.1985", "female")]
    assert await fsm_context.get_state() is None


@pytest.mark.asyncio
async def test_choose_gender_business_rule_failure_resets_to_birth_date_state(fsm_context):
    """Regression test for the aiogram-expert-flagged retry trap: a
    format-valid but business-invalid birth date (e.g. future date) only
    fails inside the service call made from choose_gender. Before the fix,
    the user was left stuck in ProfilePersonalDataStates.gender re-tapping
    the same failing gender buttons forever. This test would have FAILED
    against the pre-fix code, since it asserts the state actually moves
    back to birth_date, not just that an error was shown."""
    current_user = _client_user()
    client_management = FakeClientManagement(
        current_user, raise_error=InvalidBirthDateError("Дата рождения не может быть в будущем.")
    )
    router = _router(client_management)
    choose_gender = _get_handler(router.callback_query, "choose_gender")

    await fsm_context.set_state(ProfilePersonalDataStates.gender)
    await fsm_context.update_data(birth_date="01.01.2999")

    callback = _callback(data="reg_gender:male")
    await choose_gender(callback, GenderCB(value="male"), fsm_context, current_user=current_user)

    assert await fsm_context.get_state() == ProfilePersonalDataStates.birth_date
    callback.answer.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()
    args, kwargs = callback.message.edit_text.call_args
    assert "Дата рождения не может быть в будущем." in args[0]
