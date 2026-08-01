"""Handler-level tests for the reordered registration FSM (phone -> name_conflict
(for existing unclaimed users) / full_name (for brand-new users) -> confirm_register).

Handlers are extracted directly from the router built by create_reg_router,
mirroring the FSM setup used in test_appointment_creation_fsm_flows.py.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

import bot.handlers.registration as registration_module
from bot.handlers.registration import create_reg_router
from bot.keyboards.utils.gender_cb import GenderCB
from bot.keyboards.utils.language_cb import LanguageCB
from bot.models.clinic import Clinic
from bot.models.user import User
from bot.states.register_states import RegisterStates
from bot.utils.role import Role


class FakeUserRepository:
    def __init__(self, existing_clients=None):
        self.users_by_id = {}
        self.next_id = 1
        if existing_clients:
            for client in existing_clients:
                self.users_by_id[client.ID] = client

    async def user_exists(self, telegram_user_id):
        return any(u.telegram_user_id == telegram_user_id for u in self.users_by_id.values())

    async def get_client_by_phone(self, phone):
        return next((u for u in self.users_by_id.values() if u.phone == phone), None)

    async def get_client_by_id(self, user_id):
        return self.users_by_id.get(user_id)

    async def update_client(self, user_id, user):
        self.users_by_id[user_id] = user

    async def update_user_telegram_id(self, user_id, telegram_user_id, gender=None, birth_date=None):
        user = self.users_by_id[user_id]
        user.telegram_user_id = telegram_user_id
        user.gender = gender
        user.birth_date = birth_date

    async def create_user(self, user):
        user.ID = self.next_id
        self.users_by_id[self.next_id] = user
        self.next_id += 1


class FakeUserSettingsRepository:
    def __init__(self):
        self.language_updates = []

    async def set_language(self, user_id, language):
        self.language_updates.append((user_id, language))


class FakeStaffRepository:
    async def get_staff(self, telegram_user_id):
        return None


class FakeClinicRepository:
    def __init__(self, clinics=None):
        self.clinics_by_token = {c.token: c for c in (clinics or [])}

    async def get_clinic_by_token(self, token):
        return self.clinics_by_token.get(token)

    async def get_only_clinic(self):
        clinics = list(self.clinics_by_token.values())
        if len(clinics) != 1:
            return None
        return clinics[0]


class FakeClientClinicRepository:
    def __init__(self):
        self.links = set()

    async def link_client_to_clinic(self, client_id, clinic_id):
        self.links.add((client_id, clinic_id))

    async def client_linked_to_clinic(self, client_id, clinic_id):
        return (client_id, clinic_id) in self.links


class FakeClientNotificationService:
    def __init__(self):
        self.registration_name_changes = []

    async def notify_admins_name_changed_on_registration(self, clinic_id, stored_name, new_name, client_phone):
        self.registration_name_changes.append((clinic_id, stored_name, new_name, client_phone))


class FakeRegistrationBot:
    """Stands in for bot.loader.get_bot() so final_reg doesn't hit the real
    aiogram Bot / aiohttp session (see test_refresh_command_menus.py for the
    same get_bot-faking convention)."""

    async def set_my_commands(self, commands, scope):
        pass


def _get_handler(observer, name):
    for handler in observer.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"Handler {name!r} not found")


@pytest.fixture
def memory_storage():
    return MemoryStorage()


@pytest.fixture
def fsm_context(memory_storage):
    return FSMContext(storage=memory_storage, key=(1, 1))


@pytest.fixture
def existing_client():
    return User(
        ID=1,
        full_name="Иван Иванов",
        phone="+998901234567",
        role=Role.CLIENT,
        clinic_id=1,
        clinic_name="Клиника Тест",
    )


@pytest.fixture
def notification_service():
    return FakeClientNotificationService()


@pytest.fixture(autouse=True)
def _patch_get_bot(monkeypatch):
    monkeypatch.setattr(registration_module, "get_bot", lambda: FakeRegistrationBot())


def _build_router(existing_clients, notification_service, clinic_repo=None, client_clinic_repo=None):
    user_repo = FakeUserRepository(existing_clients=existing_clients)
    user_settings_repo = FakeUserSettingsRepository()
    router = create_reg_router(
        user_repo, clinic_repo=clinic_repo, staff_repo=FakeStaffRepository(),
        client_notification_service=notification_service, user_settings_repo=user_settings_repo,
        client_clinic_repo=client_clinic_repo,
    )
    router.user_settings_repo = user_settings_repo
    return router, user_repo


def _message(text=None, contact=None):
    message = MagicMock()
    message.text = text
    message.contact = contact
    message.from_user.id = 999
    message.answer = AsyncMock()
    return message


def _command(args=None):
    command = MagicMock()
    command.args = args
    return command


def _callback(data=None):
    callback = MagicMock()
    callback.data = data
    callback.from_user.id = 999
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()
    return callback


@pytest.mark.asyncio
async def test_get_phone_not_found_moves_to_full_name_without_existing_user(fsm_context, notification_service):
    router, _ = _build_router(existing_clients=[], notification_service=notification_service)
    get_phone = _get_handler(router.message, "get_phone")

    await fsm_context.set_state(RegisterStates.phone)
    await fsm_context.update_data(clinic_id=1, clinic_name="Клиника Тест")

    contact = MagicMock()
    contact.phone_number = "901234567"
    message = _message(contact=contact)

    await get_phone(message, fsm_context)

    assert await fsm_context.get_state() == RegisterStates.full_name
    data = await fsm_context.get_data()
    assert "existing_user_id" not in data
    message.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_phone_found_unclaimed_moves_to_name_conflict(fsm_context, existing_client, notification_service):
    router, _ = _build_router(existing_clients=[existing_client], notification_service=notification_service)
    get_phone = _get_handler(router.message, "get_phone")

    await fsm_context.set_state(RegisterStates.phone)
    await fsm_context.update_data(clinic_id=1, clinic_name="Клиника Тест")

    contact = MagicMock()
    contact.phone_number = existing_client.phone
    contact.user_id = 999
    message = _message(contact=contact)

    await get_phone(message, fsm_context)

    assert await fsm_context.get_state() == RegisterStates.name_conflict
    data = await fsm_context.get_data()
    assert data["existing_user_id"] == existing_client.ID
    assert data["existing_full_name"] == existing_client.full_name
    sent_text = message.answer.call_args.args[0]
    assert existing_client.full_name in sent_text


@pytest.mark.asyncio
async def test_get_phone_rejects_contact_owner_mismatch(fsm_context, existing_client, notification_service):
    router, _ = _build_router(existing_clients=[existing_client], notification_service=notification_service)
    get_phone = _get_handler(router.message, "get_phone")

    await fsm_context.set_state(RegisterStates.phone)
    await fsm_context.update_data(clinic_id=1, clinic_name="Клиника Тест")

    contact = MagicMock()
    contact.phone_number = existing_client.phone
    contact.user_id = 111
    message = _message(contact=contact)

    await get_phone(message, fsm_context)

    assert await fsm_context.get_state() == RegisterStates.phone
    data = await fsm_context.get_data()
    assert "existing_user_id" not in data
    sent_text = message.answer.call_args.args[0]
    assert "чужой контакт" in sent_text


@pytest.mark.asyncio
async def test_name_conflict_yes_moves_to_full_name_without_service_calls(
        fsm_context, existing_client, notification_service):
    router, user_repo = _build_router(existing_clients=[existing_client], notification_service=notification_service)
    confirm_yes = _get_handler(router.callback_query, "confirm_name_conflict_yes")

    await fsm_context.set_state(RegisterStates.name_conflict)
    await fsm_context.update_data(
        clinic_id=1,
        phone=existing_client.phone,
        existing_user_id=existing_client.ID,
        existing_full_name=existing_client.full_name,
    )

    callback = _callback(data="reg_name_conflict_yes")

    await confirm_yes(callback, fsm_context)

    assert await fsm_context.get_state() == RegisterStates.full_name
    assert user_repo.users_by_id[existing_client.ID].full_name == existing_client.full_name
    assert notification_service.registration_name_changes == []


@pytest.mark.asyncio
async def test_get_full_name_with_existing_user_applies_new_name_and_notifies_admins(
        fsm_context, existing_client, notification_service):
    router, user_repo = _build_router(existing_clients=[existing_client], notification_service=notification_service)
    get_full_name = _get_handler(router.message, "get_full_name")
    get_birth_date = _get_handler(router.message, "get_birth_date")
    choose_gender = _get_handler(router.callback_query, "choose_gender")
    original_full_name = existing_client.full_name

    await fsm_context.set_state(RegisterStates.full_name)
    await fsm_context.update_data(
        clinic_id=1,
        phone=existing_client.phone,
        existing_user_id=existing_client.ID,
        existing_full_name=original_full_name,
    )

    message = _message(text="Петр Петров")

    await get_full_name(message, fsm_context)

    assert await fsm_context.get_state() == RegisterStates.birth_date
    data = await fsm_context.get_data()
    assert data["full_name"] == "Петр Петров"
    assert user_repo.users_by_id[existing_client.ID].full_name == "Петр Петров"
    assert notification_service.registration_name_changes == [
        (1, original_full_name, "Петр Петров", existing_client.phone)
    ]

    # Drive the rest of the new birth_date -> gender -> confirm_register path.
    await get_birth_date(_message(text="05.03.1990"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.gender
    data = await fsm_context.get_data()
    assert data["birth_date"] == "05.03.1990"

    await choose_gender(_callback(data="reg_gender:male"), GenderCB(value="male"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.confirm_register
    data = await fsm_context.get_data()
    assert data["gender"] == "male"


@pytest.mark.asyncio
async def test_get_full_name_without_existing_user_skips_service_calls(fsm_context, notification_service):
    router, user_repo = _build_router(existing_clients=[], notification_service=notification_service)
    get_full_name = _get_handler(router.message, "get_full_name")
    get_birth_date = _get_handler(router.message, "get_birth_date")
    choose_gender = _get_handler(router.callback_query, "choose_gender")

    await fsm_context.set_state(RegisterStates.full_name)
    await fsm_context.update_data(clinic_id=1, phone="+998901234567")

    message = _message(text="Иван Иванов")

    await get_full_name(message, fsm_context)

    assert await fsm_context.get_state() == RegisterStates.birth_date
    data = await fsm_context.get_data()
    assert data["full_name"] == "Иван Иванов"
    assert notification_service.registration_name_changes == []

    # Drive the rest of the new birth_date -> gender -> confirm_register path.
    await get_birth_date(_message(text="12.11.1985"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.gender
    data = await fsm_context.get_data()
    assert data["birth_date"] == "12.11.1985"

    await choose_gender(_callback(data="reg_gender:female"), GenderCB(value="female"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.confirm_register
    data = await fsm_context.get_data()
    assert data["gender"] == "female"


@pytest.mark.asyncio
async def test_name_conflict_no_reverts_to_existing_name(fsm_context, existing_client, notification_service):
    router, _ = _build_router(existing_clients=[existing_client], notification_service=notification_service)
    confirm_no = _get_handler(router.callback_query, "confirm_name_conflict_no")
    get_birth_date = _get_handler(router.message, "get_birth_date")
    choose_gender = _get_handler(router.callback_query, "choose_gender")

    await fsm_context.set_state(RegisterStates.name_conflict)
    await fsm_context.update_data(
        clinic_id=1,
        phone=existing_client.phone,
        full_name="Петр Петров",
        existing_user_id=existing_client.ID,
        existing_full_name=existing_client.full_name,
    )

    callback = _callback(data="reg_name_conflict_no")

    await confirm_no(callback, fsm_context)

    assert await fsm_context.get_state() == RegisterStates.birth_date
    data = await fsm_context.get_data()
    assert data["full_name"] == existing_client.full_name

    # Drive the rest of the new birth_date -> gender -> confirm_register path.
    await get_birth_date(_message(text="01.01.2000"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.gender
    data = await fsm_context.get_data()
    assert data["birth_date"] == "01.01.2000"

    await choose_gender(_callback(data="reg_gender:male"), GenderCB(value="male"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.confirm_register
    data = await fsm_context.get_data()
    assert data["gender"] == "male"


@pytest.mark.asyncio
async def test_final_reg_new_user_creates_client(fsm_context, notification_service):
    router, user_repo = _build_router(existing_clients=[], notification_service=notification_service)
    final_reg = _get_handler(router.callback_query, "final_reg")

    await fsm_context.set_state(RegisterStates.confirm_register)
    await fsm_context.update_data(
        clinic_id=1,
        clinic_name="Клиника Тест",
        phone="+998901234567",
        full_name="Иван Иванов",
    )

    callback = _callback(data="reg_confirm")

    await final_reg(callback, fsm_context)

    created = next(u for u in user_repo.users_by_id.values() if u.full_name == "Иван Иванов")
    assert created.telegram_user_id == 999
    assert notification_service.registration_name_changes == []


@pytest.mark.asyncio
async def test_final_reg_new_user_links_client_to_clinic(fsm_context, notification_service):
    client_clinic_repo = FakeClientClinicRepository()
    router, user_repo = _build_router(
        existing_clients=[], notification_service=notification_service,
        client_clinic_repo=client_clinic_repo,
    )
    final_reg = _get_handler(router.callback_query, "final_reg")

    await fsm_context.set_state(RegisterStates.confirm_register)
    await fsm_context.update_data(
        clinic_id=1,
        clinic_name="Клиника Тест",
        phone="+998901234567",
        full_name="Иван Иванов",
    )

    callback = _callback(data="reg_confirm")

    await final_reg(callback, fsm_context)

    created = next(u for u in user_repo.users_by_id.values() if u.full_name == "Иван Иванов")
    assert await client_clinic_repo.client_linked_to_clinic(created.ID, 1) is True


@pytest.mark.asyncio
async def test_final_reg_existing_user_no_conflict_no_edit_saves_name(
        fsm_context, existing_client, notification_service):
    router, user_repo = _build_router(existing_clients=[existing_client], notification_service=notification_service)
    final_reg = _get_handler(router.callback_query, "final_reg")

    await fsm_context.set_state(RegisterStates.confirm_register)
    await fsm_context.update_data(
        clinic_id=1,
        clinic_name="Клиника Тест",
        phone=existing_client.phone,
        full_name=existing_client.full_name,
        existing_user_id=existing_client.ID,
        existing_full_name=existing_client.full_name,
    )

    callback = _callback(data="reg_confirm")

    await final_reg(callback, fsm_context)

    assert user_repo.users_by_id[existing_client.ID].full_name == existing_client.full_name
    assert user_repo.users_by_id[existing_client.ID].telegram_user_id == 999
    assert notification_service.registration_name_changes == []


@pytest.mark.asyncio
async def test_final_reg_existing_user_conflict_yes_saves_name_and_notifies(
        fsm_context, existing_client, notification_service):
    router, user_repo = _build_router(existing_clients=[existing_client], notification_service=notification_service)
    confirm_yes = _get_handler(router.callback_query, "confirm_name_conflict_yes")
    get_full_name = _get_handler(router.message, "get_full_name")
    final_reg = _get_handler(router.callback_query, "final_reg")
    original_full_name = existing_client.full_name

    await fsm_context.set_state(RegisterStates.name_conflict)
    await fsm_context.update_data(
        clinic_id=1,
        clinic_name="Клиника Тест",
        phone=existing_client.phone,
        existing_user_id=existing_client.ID,
        existing_full_name=original_full_name,
    )

    await confirm_yes(_callback(data="reg_name_conflict_yes"), fsm_context)
    await get_full_name(_message(text="Петр Петров"), fsm_context)
    await final_reg(_callback(data="reg_confirm"), fsm_context)

    assert user_repo.users_by_id[existing_client.ID].full_name == "Петр Петров"
    assert user_repo.users_by_id[existing_client.ID].telegram_user_id == 999
    assert notification_service.registration_name_changes == [
        (1, original_full_name, "Петр Петров", existing_client.phone)
    ]


@pytest.mark.asyncio
async def test_final_reg_existing_user_conflict_no_then_edit_saves_edited_name_without_notify(
        fsm_context, existing_client, notification_service):
    router, user_repo = _build_router(existing_clients=[existing_client], notification_service=notification_service)
    confirm_no = _get_handler(router.callback_query, "confirm_name_conflict_no")
    final_reg = _get_handler(router.callback_query, "final_reg")

    await fsm_context.set_state(RegisterStates.name_conflict)
    await fsm_context.update_data(
        clinic_id=1,
        phone=existing_client.phone,
        clinic_name="Клиника Тест",
        full_name="Петр Петров",
        existing_user_id=existing_client.ID,
        existing_full_name=existing_client.full_name,
    )

    await confirm_no(_callback(data="reg_name_conflict_no"), fsm_context)

    await fsm_context.update_data(full_name="Сидоров Сидор")

    await final_reg(_callback(data="reg_confirm"), fsm_context)

    assert user_repo.users_by_id[existing_client.ID].full_name == "Сидоров Сидор"
    assert user_repo.users_by_id[existing_client.ID].telegram_user_id == 999
    assert notification_service.registration_name_changes == []


@pytest.mark.asyncio
async def test_final_reg_existing_user_no_conflict_then_edit_saves_edited_name_without_notify(
        fsm_context, existing_client, notification_service):
    router, user_repo = _build_router(existing_clients=[existing_client], notification_service=notification_service)
    final_reg = _get_handler(router.callback_query, "final_reg")

    await fsm_context.set_state(RegisterStates.confirm_register)
    await fsm_context.update_data(
        clinic_id=1,
        phone=existing_client.phone,
        clinic_name="Клиника Тест",
        full_name="Сидоров Сидор",
        existing_user_id=existing_client.ID,
        existing_full_name=existing_client.full_name,
    )

    await final_reg(_callback(data="reg_confirm"), fsm_context)

    assert user_repo.users_by_id[existing_client.ID].full_name == "Сидоров Сидор"
    assert user_repo.users_by_id[existing_client.ID].telegram_user_id == 999
    assert notification_service.registration_name_changes == []


@pytest.mark.asyncio
async def test_start_guest_with_valid_token_sends_language_prompt(
        fsm_context, notification_service):
    clinic = Clinic(name="Клиника Тест", token="abc123", clinic_id=1)
    clinic_repo = FakeClinicRepository(clinics=[clinic])
    router, _ = _build_router(
        existing_clients=[], notification_service=notification_service, clinic_repo=clinic_repo,
    )
    start_guest = _get_handler(router.message, "start_guest")

    message = _message()

    await start_guest(message, fsm_context, _command(args="abc123"))

    assert await fsm_context.get_state() == RegisterStates.language
    lang_call = next(
        call for call in message.answer.call_args_list
        if call.args and "Tilni tanlang" in call.args[0]
    )
    reply_markup = lang_call.kwargs["reply_markup"]
    assert reply_markup.inline_keyboard[0][0].callback_data == LanguageCB(value="ru").pack()
    assert reply_markup.inline_keyboard[0][1].callback_data == LanguageCB(value="uz").pack()


@pytest.mark.asyncio
async def test_start_guest_without_token_resolves_the_only_clinic(
        fsm_context, notification_service):
    # Plain "/start", no QR / invite link payload at all: with one clinic
    # per database, registration must still work by falling back to that
    # single clinic instead of requiring a token.
    clinic = Clinic(name="Клиника Тест", token="abc123", clinic_id=1)
    clinic_repo = FakeClinicRepository(clinics=[clinic])
    router, _ = _build_router(
        existing_clients=[], notification_service=notification_service, clinic_repo=clinic_repo,
    )
    start_guest = _get_handler(router.message, "start_guest")

    message = _message()

    await start_guest(message, fsm_context, _command(args=None))

    data = await fsm_context.get_data()
    assert data["clinic_id"] == 1
    assert data["clinic_name"] == "Клиника Тест"
    assert await fsm_context.get_state() == RegisterStates.language


@pytest.mark.asyncio
async def test_start_guest_with_unknown_token_falls_back_to_the_only_clinic(
        fsm_context, notification_service):
    # An outdated / mismatched token (old QR code, stale share link) must
    # still resolve, the same as no token at all -- as long as this
    # database has exactly one clinic.
    clinic = Clinic(name="Клиника Тест", token="abc123", clinic_id=1)
    clinic_repo = FakeClinicRepository(clinics=[clinic])
    router, _ = _build_router(
        existing_clients=[], notification_service=notification_service, clinic_repo=clinic_repo,
    )
    start_guest = _get_handler(router.message, "start_guest")

    message = _message()

    await start_guest(message, fsm_context, _command(args="some-old-token-that-no-longer-matches"))

    data = await fsm_context.get_data()
    assert data["clinic_id"] == 1
    assert data["clinic_name"] == "Клиника Тест"


@pytest.mark.asyncio
async def test_start_guest_without_token_and_no_clinic_seeded_rejects(
        fsm_context, notification_service):
    # Defensive edge case: an empty (not-yet-seeded) database must not
    # silently guess a clinic.
    clinic_repo = FakeClinicRepository(clinics=[])
    router, _ = _build_router(
        existing_clients=[], notification_service=notification_service, clinic_repo=clinic_repo,
    )
    start_guest = _get_handler(router.message, "start_guest")

    message = _message()

    await start_guest(message, fsm_context, _command(args=None))

    message.answer.assert_awaited_once()
    sent_text = message.answer.call_args.args[0]
    assert "недействительна" in sent_text


@pytest.mark.asyncio
async def test_show_registration_guide_sends_contact_button_instructions(fsm_context, notification_service):
    router, _ = _build_router(existing_clients=[], notification_service=notification_service)
    show_registration_guide = _get_handler(router.callback_query, "show_registration_guide")

    callback = _callback(data="reg_guide")

    await show_registration_guide(callback, fsm_context)

    callback.message.edit_text.assert_awaited_once()
    sent_text = callback.message.edit_text.call_args.args[0]
    assert "📱 Отправить контакт" in sent_text
    assert "вручную" in sent_text.lower()
    assert "нельзя" in sent_text.lower()
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_rescanning_qr_clears_stale_fsm_data_before_new_registration(
        fsm_context, existing_client, notification_service):
    clinic = Clinic(name="Клиника Тест", token="abc123", clinic_id=1)
    clinic_repo = FakeClinicRepository(clinics=[clinic])
    router, user_repo = _build_router(
        existing_clients=[existing_client],
        notification_service=notification_service,
        clinic_repo=clinic_repo,
    )
    start_guest = _get_handler(router.message, "start_guest")
    choose_language = _get_handler(router.callback_query, "choose_language")
    get_phone = _get_handler(router.message, "get_phone")

    # First attempt: guest scans QR, picks a language, sends contact A ->
    # resolves to an existing unclaimed user, moving into the name_conflict state.
    await start_guest(_message(), fsm_context, _command(args="abc123"))
    await choose_language(_callback(data="reg_lang:ru"), LanguageCB(value="ru"), fsm_context)

    contact_a = MagicMock()
    contact_a.phone_number = existing_client.phone
    contact_a.user_id = 999
    await get_phone(_message(contact=contact_a), fsm_context)

    assert await fsm_context.get_state() == RegisterStates.name_conflict
    data = await fsm_context.get_data()
    assert data["existing_user_id"] == existing_client.ID

    # Guest abandons the Да/Нет prompt and re-scans the SAME QR link instead.
    await start_guest(_message(), fsm_context, _command(args="abc123"))
    await choose_language(_callback(data="reg_lang:ru"), LanguageCB(value="ru"), fsm_context)

    # Second attempt: a genuinely new contact B, unrelated to user X.
    contact_b = MagicMock()
    contact_b.phone_number = "+998907654321"
    await get_phone(_message(contact=contact_b), fsm_context)

    assert await fsm_context.get_state() == RegisterStates.full_name
    data = await fsm_context.get_data()
    assert "existing_user_id" not in data
    assert "existing_full_name" not in data


# --- reclaimed user, full end-to-end path through the new birth_date/gender
# states (Option A: reclaimed users are also prompted for both) ---

@pytest.mark.asyncio
async def test_reclaimed_user_conflict_yes_full_flow_persists_birth_date_and_gender(
        fsm_context, existing_client, notification_service):
    router, user_repo = _build_router(existing_clients=[existing_client], notification_service=notification_service)
    confirm_yes = _get_handler(router.callback_query, "confirm_name_conflict_yes")
    get_full_name = _get_handler(router.message, "get_full_name")
    get_birth_date = _get_handler(router.message, "get_birth_date")
    choose_gender = _get_handler(router.callback_query, "choose_gender")
    final_reg = _get_handler(router.callback_query, "final_reg")

    await fsm_context.set_state(RegisterStates.name_conflict)
    await fsm_context.update_data(
        clinic_id=1,
        clinic_name="Клиника Тест",
        phone=existing_client.phone,
        existing_user_id=existing_client.ID,
        existing_full_name=existing_client.full_name,
    )

    await confirm_yes(_callback(data="reg_name_conflict_yes"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.full_name

    await get_full_name(_message(text="Петр Петров"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.birth_date

    await get_birth_date(_message(text="05.03.1990"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.gender

    await choose_gender(_callback(data="reg_gender:male"), GenderCB(value="male"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.confirm_register

    await final_reg(_callback(data="reg_confirm"), fsm_context)

    stored = user_repo.users_by_id[existing_client.ID]
    assert stored.full_name == "Петр Петров"
    assert stored.telegram_user_id == 999
    assert stored.birth_date == "1990-03-05"
    assert stored.gender == "male"


@pytest.mark.asyncio
async def test_reclaimed_user_conflict_no_full_flow_persists_birth_date_and_gender(
        fsm_context, existing_client, notification_service):
    router, user_repo = _build_router(existing_clients=[existing_client], notification_service=notification_service)
    confirm_no = _get_handler(router.callback_query, "confirm_name_conflict_no")
    get_birth_date = _get_handler(router.message, "get_birth_date")
    choose_gender = _get_handler(router.callback_query, "choose_gender")
    final_reg = _get_handler(router.callback_query, "final_reg")

    await fsm_context.set_state(RegisterStates.name_conflict)
    await fsm_context.update_data(
        clinic_id=1,
        clinic_name="Клиника Тест",
        phone=existing_client.phone,
        existing_user_id=existing_client.ID,
        existing_full_name=existing_client.full_name,
    )

    await confirm_no(_callback(data="reg_name_conflict_no"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.birth_date

    await get_birth_date(_message(text="12.11.1985"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.gender

    await choose_gender(_callback(data="reg_gender:female"), GenderCB(value="female"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.confirm_register

    await final_reg(_callback(data="reg_confirm"), fsm_context)

    stored = user_repo.users_by_id[existing_client.ID]
    assert stored.full_name == existing_client.full_name
    assert stored.telegram_user_id == 999
    assert stored.birth_date == "1985-11-12"
    assert stored.gender == "female"


# --- language selection ---

@pytest.mark.asyncio
async def test_choose_language_uz_moves_to_phone_and_sends_uz_prompts(fsm_context, notification_service):
    router, _ = _build_router(existing_clients=[], notification_service=notification_service)
    choose_language = _get_handler(router.callback_query, "choose_language")

    await fsm_context.set_state(RegisterStates.language)
    await fsm_context.update_data(clinic_id=1, clinic_name="Клиника Тест")

    callback = _callback(data="reg_lang:uz")

    await choose_language(callback, LanguageCB(value="uz"), fsm_context)

    assert await fsm_context.get_state() == RegisterStates.phone
    data = await fsm_context.get_data()
    assert data["language"] == "uz"

    sent_texts = [call.args[0] for call in callback.message.answer.call_args_list if call.args]
    assert any("ro'yxatdan o'ting" in text for text in sent_texts)
    assert any("Kontaktingizni yuboring" in text for text in sent_texts)


@pytest.mark.asyncio
async def test_choose_language_ru_sends_ru_prompts(fsm_context, notification_service):
    router, _ = _build_router(existing_clients=[], notification_service=notification_service)
    choose_language = _get_handler(router.callback_query, "choose_language")

    await fsm_context.set_state(RegisterStates.language)
    await fsm_context.update_data(clinic_id=1, clinic_name="Клиника Тест")

    callback = _callback(data="reg_lang:ru")

    await choose_language(callback, LanguageCB(value="ru"), fsm_context)

    data = await fsm_context.get_data()
    assert data["language"] == "ru"

    sent_texts = [call.args[0] for call in callback.message.answer.call_args_list if call.args]
    assert any("Пройдите регистрацию" in text for text in sent_texts)
    assert any("Отправьте ваш контакт" in text for text in sent_texts)


@pytest.mark.asyncio
async def test_full_flow_uz_language_choice_reaches_register(fsm_context, notification_service):
    clinic = Clinic(name="Клиника Тест", token="abc123", clinic_id=1)
    clinic_repo = FakeClinicRepository(clinics=[clinic])
    router, user_repo = _build_router(
        existing_clients=[], notification_service=notification_service, clinic_repo=clinic_repo,
    )
    start_guest = _get_handler(router.message, "start_guest")
    choose_language = _get_handler(router.callback_query, "choose_language")
    get_phone = _get_handler(router.message, "get_phone")
    get_full_name = _get_handler(router.message, "get_full_name")
    get_birth_date = _get_handler(router.message, "get_birth_date")
    choose_gender = _get_handler(router.callback_query, "choose_gender")
    final_reg = _get_handler(router.callback_query, "final_reg")

    await start_guest(_message(), fsm_context, _command(args="abc123"))
    assert await fsm_context.get_state() == RegisterStates.language

    await choose_language(_callback(data="reg_lang:uz"), LanguageCB(value="uz"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.phone

    contact = MagicMock()
    contact.phone_number = "901234567"
    await get_phone(_message(contact=contact), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.full_name

    await get_full_name(_message(text="Иван Иванов"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.birth_date

    await get_birth_date(_message(text="05.03.1990"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.gender

    await choose_gender(_callback(data="reg_gender:male"), GenderCB(value="male"), fsm_context)
    assert await fsm_context.get_state() == RegisterStates.confirm_register

    await final_reg(_callback(data="reg_confirm"), fsm_context)

    created = next(u for u in user_repo.users_by_id.values() if u.full_name == "Иван Иванов")
    assert router.user_settings_repo.language_updates == [(created.ID, "uz")]

