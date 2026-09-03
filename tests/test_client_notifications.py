import asyncio

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


class BlockingTelegramNotifier(FakeTelegramNotifier):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def send_message(self, chat_id, text, reply_markup=None, reply_to_message_id=None):
        self.started.set()
        await self.release.wait()
        return await super().send_message(chat_id, text, reply_markup, reply_to_message_id)


class FakeUserRepo:
    def __init__(self, staff, clients=None, clients_missing_personal_data=None, notification_staff=None):
        self.staff = staff
        self.clients = clients if clients is not None else (clients_missing_personal_data or [])
        self.clients_missing_personal_data = clients_missing_personal_data or []
        self.notification_staff = staff if notification_staff is None else notification_staff

    async def get_staff_users_by_clinic_id(self, clinic_id):
        return self.staff

    async def get_clinic_notification_recipients(self, clinic_id):
        return self.notification_staff

    async def get_clients_missing_personal_data(self):
        return self.clients_missing_personal_data

    async def get_all_clients(self):
        return self.clients


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
async def test_name_change_notifications_use_only_clinic_scope_recipients():
    clinic_admin = _admin(telegram_user_id=100, ID=2)
    own_scope_staff = _admin(telegram_user_id=200, ID=3)
    notifier = FakeTelegramNotifier()
    repo = FakeUserRepo(
        [clinic_admin, own_scope_staff],
        notification_staff=[clinic_admin],
    )
    service = ClientNotificationService(notifier, repo)

    await service.notify_admins_name_changed_on_registration(
        clinic_id=1, stored_name="Иванов Иван", new_name="Петров Петр", client_phone="+998901234567",
    )

    assert [message['chat_id'] for message in notifier.sent_messages] == [100]


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
async def test_broadcast_clients_sends_raw_approved_text_to_every_client_with_telegram_id():
    clients = [
        _client(telegram_user_id=100, ID=1),
        _client(telegram_user_id=200, ID=2),
    ]
    notifier = FakeTelegramNotifier()
    repo = FakeUserRepo(staff=[], clients=clients)
    service = ClientNotificationService(notifier, repo)
    text = (
        "Уважаемые клиенты! 👋\n\n"
        "Хорошие новости: отпуск и ремонтные работы завершены.\n"
        "Уже с субботы, 5 сентября, мы снова работаем и готовы принимать пациентов.\n\n"
        "Для записи напишите нам в бот! 📲"
    )

    summary = await service.broadcast_clients(text)

    assert {message['chat_id'] for message in notifier.sent_messages} == {100, 200}
    assert [message['text'] for message in notifier.sent_messages] == [text, text]
    assert all(message['reply_markup'] is None for message in notifier.sent_messages)
    assert summary.sent == 2
    assert summary.failed == 0
    assert summary.skipped == 0


@pytest.mark.asyncio
async def test_broadcast_clients_skips_client_without_telegram_id_and_reports_it():
    """Defensive check: even though the repository query already filters out
    telegram_user_id IS NULL rows, the service must not crash or send if the
    repository ever returns one anyway."""
    clients = [
        _client(telegram_user_id=None, ID=1),
        _client(telegram_user_id=200, ID=2),
    ]
    notifier = FakeTelegramNotifier()
    repo = FakeUserRepo(staff=[], clients=clients)
    service = ClientNotificationService(notifier, repo)

    summary = await service.broadcast_clients("message")

    assert len(notifier.sent_messages) == 1
    assert notifier.sent_messages[0]['chat_id'] == 200
    assert summary.sent == 1
    assert summary.failed == 0
    assert summary.skipped == 1


@pytest.mark.asyncio
async def test_broadcast_clients_continues_past_per_recipient_failure_and_reports_it():
    clients = [
        _client(telegram_user_id=100, ID=1),
        _client(telegram_user_id=200, ID=2),
        _client(telegram_user_id=300, ID=3),
    ]
    notifier = FakeTelegramNotifier(fail_for={200})
    repo = FakeUserRepo(staff=[], clients=clients)
    service = ClientNotificationService(notifier, repo)

    summary = await service.broadcast_clients("message")

    assert {message['chat_id'] for message in notifier.sent_messages} == {100, 300}
    assert summary.sent == 2
    assert summary.failed == 1
    assert summary.skipped == 0


@pytest.mark.asyncio
async def test_broadcast_clients_escapes_customized_text_before_html_delivery():
    clients = [_client(telegram_user_id=100, ID=1)]
    notifier = FakeTelegramNotifier()
    repo = FakeUserRepo(staff=[], clients=clients)
    service = ClientNotificationService(notifier, repo)

    await service.broadcast_clients("Проверка <b>тега</b> & символа")

    assert notifier.sent_messages[0]["text"] == "Проверка &lt;b&gt;тега&lt;/b&gt; &amp; символа"
    assert notifier.sent_messages[0]["reply_markup"] is None


@pytest.mark.asyncio
async def test_start_broadcast_atomically_accepts_only_one_concurrent_batch():
    """The busy/atomic-start boundary belongs to the service, not a router
    closure: independent admin FSM contexts must not be able to launch two
    batches at the same time.  The accepted call returns its task; a busy call
    returns None."""
    notifier = BlockingTelegramNotifier()
    repo = FakeUserRepo(staff=[], clients=[_client(telegram_user_id=100, ID=1)])
    service = ClientNotificationService(notifier, repo)

    first_task, second_task = await asyncio.gather(
        service.start_broadcast("message"),
        service.start_broadcast("message"),
    )

    accepted_task = first_task or second_task
    rejected_task = second_task if first_task is not None else first_task
    assert accepted_task is not None
    assert rejected_task is None

    await asyncio.wait_for(notifier.started.wait(), timeout=1)
    notifier.release.set()
    await accepted_task

    assert [message["chat_id"] for message in notifier.sent_messages] == [100]
