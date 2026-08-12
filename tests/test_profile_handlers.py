"""Handler-level tests for the profile "change language" flow
(bot/handlers/common/profile.py), mirroring the existing reminder-settings
handler pattern: open_language_settings shows the current selection with a
checkmark, update_language_preset persists the new choice via
ClientManagement.update_language and re-renders the profile with the
updated keyboard."""

from unittest.mock import AsyncMock, MagicMock

import pytest

import bot.handlers.common.profile as profile_module
from bot.handlers.common.profile import create_profile_router
from bot.keyboards.utils.language_cb import LanguageCB
from bot.models.user import User
from bot.utils.commands import admin_commands, client_commands
from bot.utils.role import Role


class FakeClientManagement:
    def __init__(self, user: User):
        self.user = user
        self.calls = []

    async def update_language(self, user_id, language):
        self.calls.append((user_id, language))
        self.user.language = language
        return self.user


class FakeProfileBot:
    """Stands in for bot.loader.get_bot() so update_language_preset doesn't hit
    the real aiogram Bot / aiohttp session (see test_registration_handlers.py
    for the same get_bot-faking convention)."""

    def __init__(self):
        self.calls = []

    async def set_my_commands(self, commands, scope):
        self.calls.append((commands, scope.chat_id))


@pytest.fixture(autouse=True)
def _patch_get_bot(monkeypatch):
    fake_bot = FakeProfileBot()
    monkeypatch.setattr(profile_module, "get_bot", lambda: fake_bot)
    return fake_bot


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
        language="ru",
    )


def _callback(data="profile_language_settings"):
    callback = MagicMock()
    callback.data = data
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    return callback


def _router(client_management):
    return create_profile_router(client_management)


@pytest.mark.asyncio
async def test_open_language_settings_shows_current_language_with_checkmark():
    current_user = _client_user()
    router = _router(FakeClientManagement(current_user))
    open_language_settings = _get_handler(router.callback_query, "open_language_settings")

    callback = _callback()
    await open_language_settings(callback, current_user=current_user)

    reply_markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    buttons = [button for row in reply_markup.inline_keyboard for button in row]
    texts_by_value = {LanguageCB.unpack(b.callback_data).value: b.text for b in buttons if b.callback_data != "profile_back"}

    assert texts_by_value["ru"].startswith("✅")
    assert not texts_by_value["uz"].startswith("✅")
    callback.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_language_preset_persists_and_rerenders(_patch_get_bot):
    current_user = _client_user()
    client_management = FakeClientManagement(current_user)
    router = _router(client_management)
    update_language_preset = _get_handler(router.callback_query, "update_language_preset")

    callback = _callback()
    await update_language_preset(callback, LanguageCB(value="uz"), current_user=current_user)

    assert client_management.calls == [(7, "uz")]
    assert current_user.language == "uz"

    reply_markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    buttons = [button for row in reply_markup.inline_keyboard for button in row]
    texts_by_value = {LanguageCB.unpack(b.callback_data).value: b.text for b in buttons if b.callback_data != "profile_back"}

    assert texts_by_value["uz"].startswith("✅")
    assert not texts_by_value["ru"].startswith("✅")
    callback.answer.assert_awaited_once_with("Sozlamalar yangilandi")

    assert _patch_get_bot.calls == [(client_commands("uz"), 555)]


@pytest.mark.asyncio
async def test_update_language_preset_uses_middleware_role_for_rerender_and_commands(_patch_get_bot):
    current_user = _client_user()
    current_user.role = Role.ADMIN
    persisted_user = _client_user()
    client_management = FakeClientManagement(persisted_user)
    router = _router(client_management)
    update_language_preset = _get_handler(router.callback_query, "update_language_preset")

    callback = _callback()
    await update_language_preset(callback, LanguageCB(value="uz"), current_user=current_user)

    rendered_profile = callback.message.edit_text.call_args.args[0]
    assert "Foydalanuvchi turi: administrator" in rendered_profile
    assert "Foydalanuvchi turi: mijoz" not in rendered_profile
    assert _patch_get_bot.calls == [(admin_commands("uz"), 555)]
