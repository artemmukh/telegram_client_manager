import pytest

from bot.models.user import User
from bot.services.client.client_notifications import ClientNotificationService
from bot.utils.role import Role


class FakeBot:
    def __init__(self, fail_for=None):
        self.sent_messages = []
        self.fail_for = set(fail_for or [])

    async def send_message(self, chat_id, text, reply_markup=None):
        if chat_id in self.fail_for:
            raise RuntimeError("delivery failed")

        self.sent_messages.append({
            'chat_id': chat_id,
            'text': text,
            'reply_markup': reply_markup,
        })


class FakeUserRepo:
    def __init__(self, staff):
        self.staff = staff

    async def get_staff_users_by_clinic_id(self, clinic_id):
        return self.staff


def _admin(telegram_user_id, ID):
    return User(
        ID=ID,
        full_name="Админов Админ",
        phone="+998900000000",
        role=Role.ADMIN,
        telegram_user_id=telegram_user_id,
    )


@pytest.mark.asyncio
async def test_notify_admins_name_changed_on_registration_skips_no_telegram_and_survives_failure():
    admins = [
        _admin(telegram_user_id=None, ID=1),
        _admin(telegram_user_id=100, ID=2),
        _admin(telegram_user_id=200, ID=3),
    ]
    bot = FakeBot(fail_for={100})
    repo = FakeUserRepo(admins)
    service = ClientNotificationService(bot, repo)

    await service.notify_admins_name_changed_on_registration(
        clinic_id=1, stored_name="Иванов Иван", new_name="Петров Петр", client_phone="+998901234567"
    )

    assert len(bot.sent_messages) == 1
    assert bot.sent_messages[0]['chat_id'] == 200


@pytest.mark.asyncio
async def test_notify_admins_name_change_request_sends_with_keyboard_and_survives_failure():
    admins = [
        _admin(telegram_user_id=None, ID=1),
        _admin(telegram_user_id=100, ID=2),
        _admin(telegram_user_id=200, ID=3),
    ]
    bot = FakeBot(fail_for={100})
    repo = FakeUserRepo(admins)
    service = ClientNotificationService(bot, repo)
    user = User(
        ID=10,
        full_name="Иванов Иван",
        phone="+998901234567",
        role=Role.CLIENT,
        telegram_user_id=1001,
        clinic_id=1,
    )
    keyboard = object()

    await service.notify_admins_name_change_request(user, "Петров Петр", reply_markup=keyboard)

    assert len(bot.sent_messages) == 1
    assert bot.sent_messages[0]['chat_id'] == 200
    assert bot.sent_messages[0]['reply_markup'] is keyboard
