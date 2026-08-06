import pytest
from aiogram.types import InlineKeyboardMarkup

from bot.models.user import User
from bot.services.client.client_notifications import ClientNotificationService
from bot.utils.role import Role


class FakeTelegramNotifier:
    def __init__(self, fail_for=None):
        self.sent_messages = []
        self.fail_for = set(fail_for or [])

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None):
        if chat_id in self.fail_for:
            raise RuntimeError("delivery failed")

        self.sent_messages.append({
            'chat_id': chat_id,
            'text': text,
            'reply_markup': reply_markup,
        })

        return 1


class FakeUserRepo:
    def __init__(self, staff, clients_missing_personal_data=None):
        self.staff = staff
        self.clients_missing_personal_data = clients_missing_personal_data or []

    async def get_staff_users_by_clinic_id(self, clinic_id):
        return self.staff

    async def get_clients_missing_personal_data(self):
        return self.clients_missing_personal_data


def _admin(telegram_user_id, ID):
    return User(
        ID=ID,
        full_name="Админов Админ",
        phone="+998900000000",
        role=Role.ADMIN,
        telegram_user_id=telegram_user_id,
    )


def _client(telegram_user_id, ID):
    return User(
        ID=ID,
        full_name="Клиентов Клиент",
        phone="+998900000001",
        role=Role.CLIENT,
        telegram_user_id=telegram_user_id,
    )


@pytest.mark.asyncio
async def test_notify_admins_name_changed_on_registration_skips_no_telegram_and_survives_failure():
    admins = [
        _admin(telegram_user_id=None, ID=1),
        _admin(telegram_user_id=100, ID=2),
        _admin(telegram_user_id=200, ID=3),
    ]
    notifier = FakeTelegramNotifier(fail_for={100})
    repo = FakeUserRepo(admins)
    service = ClientNotificationService(notifier, repo)

    await service.notify_admins_name_changed_on_registration(
        clinic_id=1, stored_name="Иванов Иван", new_name="Петров Петр", client_phone="+998901234567"
    )

    assert len(notifier.sent_messages) == 1
    assert notifier.sent_messages[0]['chat_id'] == 200


@pytest.mark.asyncio
async def test_notify_admins_name_change_request_sends_with_keyboard_and_survives_failure():
    admins = [
        _admin(telegram_user_id=None, ID=1),
        _admin(telegram_user_id=100, ID=2),
        _admin(telegram_user_id=200, ID=3),
    ]
    notifier = FakeTelegramNotifier(fail_for={100})
    repo = FakeUserRepo(admins)
    service = ClientNotificationService(notifier, repo)
    user = User(
        ID=10,
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=1001,
        clinic_id=1,
    )
    await service.notify_admins_name_change_request(user, "Петров Петр", user_id=user.ID)

    assert len(notifier.sent_messages) == 1
    assert notifier.sent_messages[0]['chat_id'] == 200
    assert isinstance(notifier.sent_messages[0]['reply_markup'], InlineKeyboardMarkup)


@pytest.mark.asyncio
async def test_notify_admins_name_changed_on_registration_escapes_html_special_characters_in_names():
    """Both stored_name and new_name are client-typed text, sent to admins
    with parse_mode="HTML" -- an unescaped "<" would break delivery entirely
    ("can't parse entities"), not just render oddly."""
    admins = [_admin(telegram_user_id=100, ID=2)]
    notifier = FakeTelegramNotifier()
    repo = FakeUserRepo(admins)
    service = ClientNotificationService(notifier, repo)

    await service.notify_admins_name_changed_on_registration(
        clinic_id=1, stored_name="Иванов <Иван>", new_name="Петров <Петр>", client_phone="+998901234567",
    )

    assert len(notifier.sent_messages) == 1
    text = notifier.sent_messages[0]['text']
    assert "Было: Иванов &lt;Иван&gt;" in text
    assert "Стало: Петров &lt;Петр&gt;" in text
    assert "<Иван>" not in text
    assert "<Петр>" not in text


@pytest.mark.asyncio
async def test_notify_admins_name_change_request_escapes_html_special_characters_in_names():
    admins = [_admin(telegram_user_id=100, ID=2)]
    notifier = FakeTelegramNotifier()
    repo = FakeUserRepo(admins)
    service = ClientNotificationService(notifier, repo)
    user = User(
        ID=10,
        full_name="Иванов <Иван>",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=1001,
        clinic_id=1,
    )

    await service.notify_admins_name_change_request(user, "Петров <Петр>", user_id=user.ID)

    assert len(notifier.sent_messages) == 1
    text = notifier.sent_messages[0]['text']
    assert "Текущее ФИ: Иванов &lt;Иван&gt;" in text
    assert "Новое ФИ: Петров &lt;Петр&gt;" in text
    assert "<Иван>" not in text
    assert "<Петр>" not in text


@pytest.mark.asyncio
async def test_broadcast_personal_data_request_sends_to_every_client_with_telegram_id():
    clients = [
        _client(telegram_user_id=100, ID=1),
        _client(telegram_user_id=200, ID=2),
    ]
    notifier = FakeTelegramNotifier()
    repo = FakeUserRepo(staff=[], clients_missing_personal_data=clients)
    service = ClientNotificationService(notifier, repo)

    await service.broadcast_personal_data_request()

    assert {message['chat_id'] for message in notifier.sent_messages} == {100, 200}


@pytest.mark.asyncio
async def test_broadcast_personal_data_request_skips_client_without_telegram_id():
    """Defensive check: even though the repository query already filters out
    telegram_user_id IS NULL rows, the service must not crash or send if the
    repository ever returns one anyway."""
    clients = [
        _client(telegram_user_id=None, ID=1),
        _client(telegram_user_id=200, ID=2),
    ]
    notifier = FakeTelegramNotifier()
    repo = FakeUserRepo(staff=[], clients_missing_personal_data=clients)
    service = ClientNotificationService(notifier, repo)

    await service.broadcast_personal_data_request()

    assert len(notifier.sent_messages) == 1
    assert notifier.sent_messages[0]['chat_id'] == 200


@pytest.mark.asyncio
async def test_broadcast_personal_data_request_continues_past_per_recipient_failure():
    clients = [
        _client(telegram_user_id=100, ID=1),
        _client(telegram_user_id=200, ID=2),
        _client(telegram_user_id=300, ID=3),
    ]
    notifier = FakeTelegramNotifier(fail_for={200})
    repo = FakeUserRepo(staff=[], clients_missing_personal_data=clients)
    service = ClientNotificationService(notifier, repo)

    await service.broadcast_personal_data_request()

    assert {message['chat_id'] for message in notifier.sent_messages} == {100, 300}


@pytest.mark.asyncio
async def test_broadcast_personal_data_request_sends_exact_reply_markup_and_fallback_text():
    clients = [_client(telegram_user_id=100, ID=1)]
    notifier = FakeTelegramNotifier()
    repo = FakeUserRepo(staff=[], clients_missing_personal_data=clients)
    service = ClientNotificationService(notifier, repo)

    await service.broadcast_personal_data_request()

    assert len(notifier.sent_messages) == 1
    sent = notifier.sent_messages[0]
    assert isinstance(sent['reply_markup'], InlineKeyboardMarkup)
    assert "Профиль → Изменить личные данные → Добавить дату рождения и пол" in sent['text']
