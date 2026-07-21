"""Handler-level tests for the reordered registration FSM (phone -> name_conflict
(for existing unclaimed users) / full_name (for brand-new users) -> confirm_register).

Handlers are extracted directly from the router built by create_reg_router,
mirroring the FSM setup used in test_appointment_creation_fsm_flows.py.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers.registration import create_reg_router
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

    async def update_user_telegram_id(self, user_id, telegram_user_id):
        self.users_by_id[user_id].telegram_user_id = telegram_user_id

    async def create_user(self, user):
        user.ID = self.next_id
        self.users_by_id[self.next_id] = user
        self.next_id += 1


class FakeStaffRepository:
    async def get_staff(self, telegram_user_id):
        return None


class FakeClinicRepository:
    def __init__(self, clinics=None):
        self.clinics_by_token = {c.token: c for c in (clinics or [])}

    async def get_clinic_by_token(self, token):
        return self.clinics_by_token.get(token)


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


def _build_router(existing_clients, notification_service, clinic_repo=None, client_clinic_repo=None):
    user_repo = FakeUserRepository(existing_clients=existing_clients)
    router = create_reg_router(
        user_repo, clinic_repo=clinic_repo, staff_repo=FakeStaffRepository(),
        client_notification_service=notification_service, client_clinic_repo=client_clinic_repo,
    )
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

    assert await fsm_context.get_state() == RegisterStates.confirm_register
    data = await fsm_context.get_data()
    assert data["full_name"] == "Петр Петров"
    assert user_repo.users_by_id[existing_client.ID].full_name == "Петр Петров"
    assert notification_service.registration_name_changes == [
        (1, original_full_name, "Петр Петров", existing_client.phone)
    ]


@pytest.mark.asyncio
async def test_get_full_name_without_existing_user_skips_service_calls(fsm_context, notification_service):
    router, user_repo = _build_router(existing_clients=[], notification_service=notification_service)
    get_full_name = _get_handler(router.message, "get_full_name")

    await fsm_context.set_state(RegisterStates.full_name)
    await fsm_context.update_data(clinic_id=1, phone="+998901234567")

    message = _message(text="Иван Иванов")

    await get_full_name(message, fsm_context)

    assert await fsm_context.get_state() == RegisterStates.confirm_register
    data = await fsm_context.get_data()
    assert data["full_name"] == "Иван Иванов"
    assert notification_service.registration_name_changes == []


@pytest.mark.asyncio
async def test_name_conflict_no_reverts_to_existing_name(fsm_context, existing_client, notification_service):
    router, _ = _build_router(existing_clients=[existing_client], notification_service=notification_service)
    confirm_no = _get_handler(router.callback_query, "confirm_name_conflict_no")

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

    assert await fsm_context.get_state() == RegisterStates.confirm_register
    data = await fsm_context.get_data()
    assert data["full_name"] == existing_client.full_name


@pytest.mark.asyncio
async def test_final_reg_new_user_creates_client(fsm_context, notification_service):
    router, user_repo = _build_router(existing_clients=[], notification_service=notification_service)
    final_reg = _get_handler(router.callback_query, "final_reg")

    await fsm_context.set_state(RegisterStates.confirm_register)
    await fsm_context.update_data(
        clinic_id=1,
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
        full_name="Сидоров Сидор",
        existing_user_id=existing_client.ID,
        existing_full_name=existing_client.full_name,
    )

    await final_reg(_callback(data="reg_confirm"), fsm_context)

    assert user_repo.users_by_id[existing_client.ID].full_name == "Сидоров Сидор"
    assert user_repo.users_by_id[existing_client.ID].telegram_user_id == 999
    assert notification_service.registration_name_changes == []


@pytest.mark.asyncio
async def test_start_guest_with_valid_token_sends_guide_prompt_with_reg_guide_button(
        fsm_context, notification_service):
    clinic = Clinic(name="Клиника Тест", token="abc123", clinic_id=1)
    clinic_repo = FakeClinicRepository(clinics=[clinic])
    router, _ = _build_router(
        existing_clients=[], notification_service=notification_service, clinic_repo=clinic_repo,
    )
    start_guest = _get_handler(router.message, "start_guest")

    message = _message()

    await start_guest(message, fsm_context, _command(args="abc123"))

    guide_call = next(
        call for call in message.answer.call_args_list
        if call.args and "Пройдите регистрацию" in call.args[0]
    )
    reply_markup = guide_call.kwargs["reply_markup"]
    assert reply_markup.inline_keyboard[0][0].callback_data == "reg_guide"


@pytest.mark.asyncio
async def test_show_registration_guide_sends_contact_button_instructions(notification_service):
    router, _ = _build_router(existing_clients=[], notification_service=notification_service)
    show_registration_guide = _get_handler(router.callback_query, "show_registration_guide")

    callback = _callback(data="reg_guide")

    await show_registration_guide(callback)

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
    get_phone = _get_handler(router.message, "get_phone")

    # First attempt: guest scans QR, sends contact A -> resolves to an
    # existing unclaimed user, moving into the name_conflict state.
    await start_guest(_message(), fsm_context, _command(args="abc123"))

    contact_a = MagicMock()
    contact_a.phone_number = existing_client.phone
    contact_a.user_id = 999
    await get_phone(_message(contact=contact_a), fsm_context)

    assert await fsm_context.get_state() == RegisterStates.name_conflict
    data = await fsm_context.get_data()
    assert data["existing_user_id"] == existing_client.ID

    # Guest abandons the Да/Нет prompt and re-scans the SAME QR link instead.
    await start_guest(_message(), fsm_context, _command(args="abc123"))

    # Second attempt: a genuinely new contact B, unrelated to user X.
    contact_b = MagicMock()
    contact_b.phone_number = "+998907654321"
    await get_phone(_message(contact=contact_b), fsm_context)

    assert await fsm_context.get_state() == RegisterStates.full_name
    data = await fsm_context.get_data()
    assert "existing_user_id" not in data
    assert "existing_full_name" not in data

