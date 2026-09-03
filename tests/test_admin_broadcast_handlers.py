"""Handler-level coverage for the protected one-time client broadcast flow.

The callbacks are invoked directly, as in the other admin handler tests.  The
fake broadcast service never talks to Telegram; it only records calls so this
suite can prove the confirmation and in-flight guards without an external
side-effect.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.common.profile import create_profile_router
from bot.models.user import User
from bot.utils.role import Role

DEFAULT_TEXT = (
    "Уважаемые клиенты! 👋\n\n"
    "Хорошие новости: отпуск и ремонтные работы завершены.\n"
    "Уже с субботы, 5 сентября, мы снова работаем и готовы принимать пациентов.\n\n"
    "Для записи напишите нам в бот! 📲"
)


class FakeBroadcastService:
    def __init__(self):
        self.calls = []
        self.start_calls = []
        self.completed = asyncio.Event()
        self._task = None

    async def broadcast_clients(self, text):
        self.calls.append(text)
        self.completed.set()
        return SimpleNamespace(sent=1, failed=0, skipped=0)

    async def start_broadcast(self, text):
        if self._task is not None and not self._task.done():
            return None

        self.start_calls.append(text)
        task = asyncio.create_task(self.broadcast_clients(text))
        self._task = task

        def clear_finished_task(completed_task):
            if self._task is completed_task:
                self._task = None

        task.add_done_callback(clear_finished_task)
        return task


class BlockingBroadcastService(FakeBroadcastService):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def broadcast_clients(self, text):
        self.calls.append(text)
        self.started.set()
        await self.release.wait()
        self.completed.set()
        return SimpleNamespace(sent=1, failed=0, skipped=0)


class FakeState:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.states = []
        self.cleared = False

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **values):
        self.data.update(values)

    async def set_state(self, state):
        self.states.append(state)

    async def clear(self):
        self.data.clear()
        self.cleared = True


class FakeClientManagement:
    async def update_language(self, user_id, language):
        raise AssertionError("language flow is outside this test")

    async def update_reminder_preferences(self, user_id, preset):
        raise AssertionError("reminder flow is outside this test")


def _get_handler(observer, name):
    for handler in observer.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"Handler {name!r} not found")


def _user(role=Role.ADMIN, *, is_doctor=None):
    user = User(
        ID=7,
        full_name="Администратор Тестовый",
        phone="+998901234567",
        role=role,
        telegram_user_id=555,
        clinic_id=1,
        clinic_name="Клиника Тест",
        language="ru",
    )
    if is_doctor is not None:
        # Doctor and clinic-admin staff both resolve to Role.ADMIN in this
        # application.  Keep the staff distinction on the test user so both
        # approved actor types are pinned by the regression test.
        user.is_doctor = is_doctor
    return user


def _callback(data="profile_reminder_settings"):
    callback = MagicMock()
    callback.data = data
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.message.edit_reply_markup = AsyncMock()
    return callback


def _message(text):
    message = MagicMock()
    message.text = text
    message.answer = AsyncMock()
    return message


def _router(broadcast_service):
    return create_profile_router(FakeClientManagement(), broadcast_service)


def _buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


@pytest.mark.asyncio
@pytest.mark.parametrize("is_doctor", [True, False], ids=["doctor", "clinic-admin"])
async def test_broadcast_entry_is_available_to_both_admin_staff_types_but_nested_in_notification_settings(is_doctor):
    broadcast_service = FakeBroadcastService()
    router = _router(broadcast_service)
    current_user = _user(Role.ADMIN, is_doctor=is_doctor)

    profile = _get_handler(router.message, "profile")
    message = _message("/profile")
    await profile(message, current_user=current_user)
    profile_markup = message.answer.call_args.kwargs["reply_markup"]
    assert all(button.callback_data != "profile_broadcast_settings" for button in _buttons(profile_markup))

    open_reminder_settings = _get_handler(router.callback_query, "open_reminder_settings")
    callback = _callback()
    await open_reminder_settings(callback, current_user=current_user)
    settings_markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert any(button.callback_data == "profile_broadcast_settings" for button in _buttons(settings_markup))


@pytest.mark.asyncio
async def test_broadcast_entry_is_not_exposed_to_client_profile():
    router = _router(FakeBroadcastService())
    current_user = _user(Role.CLIENT)

    profile = _get_handler(router.message, "profile")
    message = _message("/profile")
    await profile(message, current_user=current_user)
    profile_markup = message.answer.call_args.kwargs["reply_markup"]
    assert all(button.callback_data != "profile_broadcast_settings" for button in _buttons(profile_markup))

    open_reminder_settings = _get_handler(router.callback_query, "open_reminder_settings")
    callback = _callback()
    await open_reminder_settings(callback, current_user=current_user)
    settings_markup = callback.message.edit_text.call_args.kwargs["reply_markup"]
    assert all(button.callback_data != "profile_broadcast_settings" for button in _buttons(settings_markup))


@pytest.mark.asyncio
async def test_broadcast_preview_uses_exact_default_text_without_starting_delivery():
    service = FakeBroadcastService()
    router = _router(service)
    preview = _get_handler(router.callback_query, "open_broadcast_preview")

    callback = _callback("profile_broadcast_settings")
    state = FakeState()
    await preview(callback, state, current_user=_user(Role.ADMIN, is_doctor=True))

    assert callback.message.edit_text.call_args.args[0] == DEFAULT_TEXT
    assert service.calls == []


@pytest.mark.asyncio
async def test_broadcast_text_edit_is_kept_in_fsm_and_used_by_preview():
    service = FakeBroadcastService()
    router = _router(service)
    edit = _get_handler(router.callback_query, "edit_broadcast_text")
    receive = _get_handler(router.message, "receive_broadcast_text")
    preview = _get_handler(router.callback_query, "open_broadcast_preview")
    current_user = _user(Role.ADMIN, is_doctor=False)

    state = FakeState()
    callback = _callback("broadcast_edit_text")
    await edit(callback, state, current_user=current_user)
    custom_text = "Изменённый <b>текст</b> & рассылки"
    await receive(_message(custom_text), state, current_user=current_user)
    await preview(_callback("profile_broadcast_settings"), state, current_user=current_user)

    assert state.data["broadcast_text"] == custom_text
    preview_callback = _callback()
    await preview(preview_callback, state, current_user=current_user)
    assert preview_callback.message.edit_text.call_args.args[0] == "Изменённый &lt;b&gt;текст&lt;/b&gt; &amp; рассылки"
    assert service.calls == []


@pytest.mark.asyncio
async def test_broadcast_requires_second_confirmation_and_cancel_does_not_start_service():
    service = FakeBroadcastService()
    router = _router(service)
    request_send = _get_handler(router.callback_query, "request_broadcast_send")
    confirm_send = _get_handler(router.callback_query, "confirm_broadcast_send")
    cancel_send = _get_handler(router.callback_query, "cancel_broadcast_send")
    current_user = _user(Role.ADMIN, is_doctor=True)

    state = FakeState({"broadcast_text": DEFAULT_TEXT})
    await request_send(_callback("broadcast_send"), state, current_user=current_user)
    assert service.calls == []

    await cancel_send(_callback("broadcast_cancel"), state, current_user=current_user)
    await asyncio.sleep(0)
    assert service.calls == []

    await request_send(_callback("broadcast_send"), state, current_user=current_user)
    await confirm_send(_callback("broadcast_confirm"), state, current_user=current_user)
    await asyncio.sleep(0)
    assert service.calls == [DEFAULT_TEXT]
    assert service.start_calls == [DEFAULT_TEXT]


@pytest.mark.asyncio
async def test_final_send_clears_fsm_and_reopening_preview_restores_exact_default_text():
    service = FakeBroadcastService()
    router = _router(service)
    request_send = _get_handler(router.callback_query, "request_broadcast_send")
    confirm_send = _get_handler(router.callback_query, "confirm_broadcast_send")
    preview = _get_handler(router.callback_query, "open_broadcast_preview")
    current_user = _user(Role.ADMIN, is_doctor=True)
    state = FakeState({"broadcast_text": "Кастомный текст"})

    await request_send(_callback("broadcast_send"), state, current_user=current_user)
    await confirm_send(_callback("broadcast_confirm"), state, current_user=current_user)
    await asyncio.wait_for(service.completed.wait(), timeout=1)
    await asyncio.sleep(0)

    assert state.cleared is True
    assert state.data == {}
    assert service.start_calls == ["Кастомный текст"]

    reopened = _callback("profile_broadcast_settings")
    await preview(reopened, state, current_user=current_user)
    assert reopened.message.edit_text.call_args.args[0] == DEFAULT_TEXT


@pytest.mark.asyncio
async def test_second_confirm_while_batch_is_running_does_not_start_duplicate_delivery():
    service = BlockingBroadcastService()
    router = _router(service)
    request_send = _get_handler(router.callback_query, "request_broadcast_send")
    confirm_send = _get_handler(router.callback_query, "confirm_broadcast_send")
    current_user = _user(Role.ADMIN, is_doctor=False)
    state = FakeState({"broadcast_text": DEFAULT_TEXT})

    await request_send(_callback("broadcast_send"), state, current_user=current_user)
    await confirm_send(_callback("broadcast_confirm"), state, current_user=current_user)
    await asyncio.wait_for(service.started.wait(), timeout=1)

    await request_send(_callback("broadcast_send"), state, current_user=current_user)
    await confirm_send(_callback("broadcast_confirm"), state, current_user=current_user)
    await asyncio.sleep(0)

    assert service.calls == [DEFAULT_TEXT]
    assert service.start_calls == [DEFAULT_TEXT]
    service.release.set()


@pytest.mark.asyncio
async def test_immediate_completion_replaces_started_status_with_final_summary():
    service = FakeBroadcastService()
    router = _router(service)
    request_send = _get_handler(router.callback_query, "request_broadcast_send")
    confirm_send = _get_handler(router.callback_query, "confirm_broadcast_send")
    state = FakeState({"broadcast_text": DEFAULT_TEXT})
    callback = _callback("broadcast_confirm")
    status_texts = []

    async def record_status(text, **kwargs):
        status_texts.append(text)

    callback.message.edit_text = record_status
    await request_send(_callback("broadcast_send"), state, current_user=_user())
    await confirm_send(callback, state, current_user=_user())
    await asyncio.wait_for(service.completed.wait(), timeout=1)
    await asyncio.sleep(0)

    assert status_texts == [
        "Рассылка запущена. После завершения здесь появится итог.",
        "Рассылка завершена. Отправлено: 1; ошибок: 0; пропущено: 0.",
    ]
    assert service.start_calls == [DEFAULT_TEXT]


@pytest.mark.asyncio
async def test_final_status_edit_failure_is_logged_and_does_not_leak_task_exception(caplog):
    service = FakeBroadcastService()
    router = _router(service)
    request_send = _get_handler(router.callback_query, "request_broadcast_send")
    confirm_send = _get_handler(router.callback_query, "confirm_broadcast_send")
    state = FakeState({"broadcast_text": DEFAULT_TEXT})
    callback = _callback("broadcast_confirm")
    status_texts = []

    async def fail_final_status(text, **kwargs):
        status_texts.append(text)
        if text.startswith("Рассылка завершена"):
            raise RuntimeError("final status edit failed")

    callback.message.edit_text = fail_final_status
    loop = asyncio.get_running_loop()
    unhandled = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
    try:
        await request_send(_callback("broadcast_send"), state, current_user=_user())
        await confirm_send(callback, state, current_user=_user())
        await asyncio.wait_for(service.completed.wait(), timeout=1)
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous_handler)

    assert status_texts[0] == "Рассылка запущена. После завершения здесь появится итог."
    assert service.start_calls == [DEFAULT_TEXT]
    assert not unhandled
    assert "broadcast" in caplog.text.lower()
