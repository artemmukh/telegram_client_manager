"""Tests for the post-appointment follow-up handlers (Да/Нет prompt).

Both "Да" and "Нет" now atomically finalize the appointment as COMPLETED via
AppointmentManagement.complete_appointment_by_admin() before doing anything
else. "Да" then re-opens the post-appointment editing window (status/service/
price corrections) on top of the now-COMPLETED appointment; "Нет" just closes
out the follow-up prompt. If another staff member's decision already landed
first (AppointmentAlreadyDecidedError), both branches show the same fixed
alert and skip their normal success rendering.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers.admin.appointment_management.appointment_completion import (
    create_admin_completion_router,
)
from bot.handlers.utils.admin_utils.appointment_decision_helpers import (
    replace_completion_sibling_prompts,
    staff_completion_result_text,
)
from bot.handlers.utils.admin_utils.appointment_helpers import build_appointment_card
from bot.keyboards.admin.record_management_kb.completion_details_cb import (
    CompletionDetailsCB,
    CompletionHideDetailsCB,
)
from bot.keyboards.admin.record_management_kb.completion_details_kb import (
    completion_details_kb,
    completion_hide_details_kb,
)
from bot.keyboards.admin.record_management_kb.completion_followup_cb import (
    CompletionFollowupCB,
)
from bot.keyboards.admin.record_management_kb.completion_sibling_details_cb import (
    CompletionSiblingDetailsCB,
    CompletionSiblingHideDetailsCB,
)
from bot.keyboards.admin.record_management_kb.completion_sibling_details_kb import (
    completion_sibling_details_kb,
    completion_sibling_hide_details_kb,
)
from bot.models.appointment import Appointment
from bot.models.appointment_notification import AppointmentNotification
from bot.models.clinic import Clinic
from bot.models.staff import Staff
from bot.models.user import User
from bot.states.admin.record_management.appointment_browser_states import (
    AppointmentBrowserStates,
)
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy
from bot.utils.role import Role

ADMIN_TELEGRAM_ID = 999
OTHER_ADMIN_TELEGRAM_ID = 1000

ALREADY_DECIDED_ALERT = "Запись уже автозавершена, вы можете скорректировать её в «Завершённые»"


@pytest.mark.parametrize(
    ("lang", "label"),
    [("ru", "Подробнее"), ("uz", "Batafsil")],
)
def test_completion_details_keyboard_uses_only_appointment_id(lang, label):
    markup = completion_details_kb(188, lang=lang)
    callback = CompletionDetailsCB.unpack(markup.inline_keyboard[0][0].callback_data)

    assert markup.inline_keyboard[0][0].text == label
    assert callback.appointment_id == 188
    assert callback.model_dump() == {"appointment_id": 188}


@pytest.mark.parametrize(
    ("lang", "label"),
    [("ru", "Скрыть"), ("uz", "Yopish")],
)
def test_completion_hide_details_keyboard_uses_only_appointment_id(lang, label):
    markup = completion_hide_details_kb(188, lang=lang)
    callback = CompletionHideDetailsCB.unpack(markup.inline_keyboard[0][0].callback_data)

    assert markup.inline_keyboard[0][0].text == label
    assert callback.appointment_id == 188
    assert callback.model_dump() == {"appointment_id": 188}


class FakeAppointmentRepository:
    def __init__(self, appointment, notifications=None):
        self.appointment = appointment
        self.status_updates = []
        self.notifications = list(notifications or [])

    async def get_appointment_by_id(self, appointment_id):
        return self.appointment

    async def get_appointments_by_doctor_and_date(self, doctor_id, date):
        return []

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.appointment.status = status
        self.status_updates.append((appointment_id, status))

    async def try_complete_appointment(self, appointment_id, decided_by_user_id, status_updated_at):
        # Deliberately does not mutate self.appointment -- AppointmentManagement.
        # complete_appointment_by_admin() applies the equivalent field updates
        # itself afterward, mirroring the real repository which only touches
        # the DB row, never the caller's Python object.
        finalized = {
            AppointmentStatus.CANCELLED,
            AppointmentStatus.COMPLETED,
            AppointmentStatus.NO_SHOW,
            AppointmentStatus.EXPIRED,
        }
        if self.appointment.status in finalized:
            return False

        self.status_updates.append((appointment_id, AppointmentStatus.COMPLETED))
        return True

    async def get_appointment_notifications(self, appointment_id, kind):
        return self.notifications


class FakeUserRepo:
    def __init__(self, admins=None):
        self.admins = admins or {
            ADMIN_TELEGRAM_ID: User(
                full_name="Петров Петр",
                phone="+998907654321",
                role=Role.ADMIN,
                telegram_user_id=ADMIN_TELEGRAM_ID,
                ID=1,
                clinic_id=1,
                clinic_name="Зуб Мудрости",
            ),
            OTHER_ADMIN_TELEGRAM_ID: User(
                full_name="Сидоров Сидор",
                phone="+998901112233",
                role=Role.ADMIN,
                telegram_user_id=OTHER_ADMIN_TELEGRAM_ID,
                ID=2,
                clinic_id=1,
                clinic_name="Зуб Мудрости",
            ),
        }
        self.by_id = {user.ID: user for user in self.admins.values()}

    async def get_user_by_telegram_id(self, telegram_user_id):
        return self.admins.get(telegram_user_id)

    async def get_user_by_id(self, user_id):
        return self.by_id.get(user_id)


class FakeStaffRepo:
    async def get_staff(self, telegram_user_id):
        return Staff(telegram_user_id=telegram_user_id, clinic_id=1, visibility_scope="own")


class FakeClinicRepo:
    async def get_clinic_by_id(self, clinic_id):
        return Clinic(clinic_id=1, name="Зуб Мудрости", token="t")


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _admin_user():
    return User(full_name="Петров Петр", phone="+998907654321", role=Role.ADMIN, telegram_user_id=ADMIN_TELEGRAM_ID, ID=1)


def _appointment(doctor_id=1):
    return Appointment(
        clinic_id=1,
        client_id=1,
        doctor_id=doctor_id,
        datetime="2026-07-10 10:00",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.CONFIRMED,
        id=1,
    )


def _callback_query(telegram_user_id=ADMIN_TELEGRAM_ID):
    callback_query = MagicMock()
    callback_query.from_user.id = telegram_user_id
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


def _router(appointment_repo, appointment_scheduler=None, notification_service=None):
    return create_admin_completion_router(
        appointment_repo, FakeUserRepo(), FakeStaffRepo(), FakeClinicRepo(),
        appointment_scheduler, notification_service,
    )


@pytest.mark.asyncio
async def test_open_edit_completes_appointment_and_renders_post_appt_card():
    appointment_repo = FakeAppointmentRepository(_appointment())
    router = _router(appointment_repo)
    open_edit = _find_handler(router, "open_edit")

    callback_query = _callback_query()
    callback_data = CompletionFollowupCB(action="edit", appointment_id=1)

    await open_edit(callback_query, callback_data, AsyncMock(), _admin_user())

    assert appointment_repo.appointment.status is AppointmentStatus.COMPLETED
    assert appointment_repo.status_updates == [(1, AppointmentStatus.COMPLETED)]

    reply_markup = callback_query.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [button.callback_data for row in reply_markup.inline_keyboard for button in row]
    assert any("finish_appointment" in cb for cb in callback_datas)


@pytest.mark.asyncio
async def test_open_edit_resyncs_jobs_when_scheduler_provided():
    appointment_repo = FakeAppointmentRepository(_appointment())
    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()
    router = _router(appointment_repo, appointment_scheduler)
    open_edit = _find_handler(router, "open_edit")

    callback_query = _callback_query()
    callback_data = CompletionFollowupCB(action="edit", appointment_id=1)

    await open_edit(callback_query, callback_data, AsyncMock(), _admin_user())

    appointment_scheduler.resync_appointment_jobs.assert_awaited_once()
    resynced_appointment = appointment_scheduler.resync_appointment_jobs.call_args.args[0]
    assert resynced_appointment.status is AppointmentStatus.COMPLETED


@pytest.mark.asyncio
async def test_open_edit_invalidates_sibling_notifications_on_success():
    appointment_repo = FakeAppointmentRepository(
        _appointment(),
        notifications=[
            AppointmentNotification(appointment_id=1, chat_id=555, message_id=777, kind="completion"),
        ],
    )
    notification_service = MagicMock()
    notification_service.resolve_recipient_language = AsyncMock(return_value="ru")
    notification_service.notifier.try_edit_message_text = AsyncMock()
    router = _router(appointment_repo, notification_service=notification_service)
    open_edit = _find_handler(router, "open_edit")

    callback_query = _callback_query()
    callback_data = CompletionFollowupCB(action="edit", appointment_id=1)

    await open_edit(callback_query, callback_data, AsyncMock(), _admin_user())

    notification_service.notifier.try_edit_message_text.assert_awaited_once()
    call = notification_service.notifier.try_edit_message_text.await_args
    assert call.kwargs["chat_id"] == 555
    assert call.kwargs["message_id"] == 777
    assert call.kwargs["text"] == "Приём №1 завершён.\nЗавершил(а): Доктор Петров Петр"


@pytest.mark.asyncio
async def test_open_edit_shows_alert_and_does_not_render_card_when_already_decided():
    appointment = _appointment()
    appointment.status = AppointmentStatus.COMPLETED
    appointment_repo = FakeAppointmentRepository(appointment)
    notification_service = MagicMock()
    notification_service.invalidate_stale_decision_message = AsyncMock()
    router = _router(appointment_repo, notification_service=notification_service)
    open_edit = _find_handler(router, "open_edit")

    callback_query = _callback_query()
    callback_query.message.chat.id = 111
    callback_query.message.message_id = 222
    callback_data = CompletionFollowupCB(action="edit", appointment_id=1)

    await open_edit(callback_query, callback_data, AsyncMock(), _admin_user())

    callback_query.answer.assert_called_once_with(ALREADY_DECIDED_ALERT, show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    assert appointment_repo.status_updates == []
    notification_service.invalidate_stale_decision_message.assert_awaited_once_with(
        111, 222,
        {"ru": "Другой сотрудник", "uz": "Boshqa xodim"},
        {"ru": "приём завершён", "uz": "qabul yakunlandi"},
        appointment_summary="Запись №1\nВремя: 10.07.2026 10:00\nУслуга: Консультация\nСтатус: ✔️ завершена",
    )


@pytest.mark.asyncio
async def test_open_edit_denies_access_to_other_doctors_appointment():
    appointment_repo = FakeAppointmentRepository(_appointment(doctor_id=1))
    router = _router(appointment_repo)
    open_edit = _find_handler(router, "open_edit")

    callback_query = _callback_query(telegram_user_id=OTHER_ADMIN_TELEGRAM_ID)
    callback_data = CompletionFollowupCB(action="edit", appointment_id=1)

    await open_edit(callback_query, callback_data, AsyncMock(), _admin_user())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    assert appointment_repo.appointment.status is AppointmentStatus.CONFIRMED


@pytest.mark.asyncio
async def test_skip_edit_finalizes_status_as_completed():
    appointment_repo = FakeAppointmentRepository(_appointment())
    router = _router(appointment_repo)
    skip_edit = _find_handler(router, "skip_edit")

    callback_query = _callback_query()
    callback_data = CompletionFollowupCB(action="skip", appointment_id=1)

    await skip_edit(callback_query, callback_data, AsyncMock(), _admin_user())

    assert appointment_repo.appointment.status is AppointmentStatus.COMPLETED
    assert appointment_repo.status_updates == [(1, AppointmentStatus.COMPLETED)]
    callback_query.message.edit_text.assert_called_once_with(
        "Приём завершён.", reply_markup=completion_details_kb(1, lang="ru"),
    )


@pytest.mark.asyncio
async def test_completion_details_edits_compact_message_to_appointment_card():
    appointment_repo = FakeAppointmentRepository(_appointment())
    details = _find_handler(_router(appointment_repo), "show_completion_details")
    callback_query = _callback_query()

    await details(callback_query, CompletionDetailsCB(appointment_id=1), _admin_user())

    callback_query.answer.assert_awaited_once_with("")
    callback_query.message.edit_text.assert_awaited_once_with(
        build_appointment_card(appointment_repo.appointment, "ru"),
        reply_markup=completion_hide_details_kb(1, lang="ru"),
    )


@pytest.mark.asyncio
async def test_hide_completion_details_restores_compact_message():
    appointment_repo = FakeAppointmentRepository(_appointment())
    hide_details = _find_handler(_router(appointment_repo), "hide_completion_details")
    callback_query = _callback_query()

    await hide_details(callback_query, CompletionHideDetailsCB(appointment_id=1), _admin_user())

    callback_query.answer.assert_awaited_once_with("")
    callback_query.message.edit_text.assert_awaited_once_with(
        "Приём завершён.", reply_markup=completion_details_kb(1, lang="ru"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "callback_data", "appointment", "telegram_user_id"),
    [
        ("show_completion_details", CompletionDetailsCB(appointment_id=1), None, ADMIN_TELEGRAM_ID),
        (
            "hide_completion_details", CompletionHideDetailsCB(appointment_id=1), _appointment(doctor_id=1),
            OTHER_ADMIN_TELEGRAM_ID,
        ),
    ],
)
async def test_completion_details_denies_missing_or_out_of_scope_appointment(
    handler_name, callback_data, appointment, telegram_user_id,
):
    handler = _find_handler(_router(FakeAppointmentRepository(appointment)), handler_name)
    callback_query = _callback_query(telegram_user_id=telegram_user_id)

    await handler(callback_query, callback_data, _admin_user())

    callback_query.answer.assert_awaited_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_skip_edit_resyncs_jobs_when_scheduler_provided():
    appointment_repo = FakeAppointmentRepository(_appointment())
    appointment_scheduler = MagicMock()
    appointment_scheduler.resync_appointment_jobs = AsyncMock()
    router = _router(appointment_repo, appointment_scheduler)
    skip_edit = _find_handler(router, "skip_edit")

    callback_query = _callback_query()
    callback_data = CompletionFollowupCB(action="skip", appointment_id=1)

    await skip_edit(callback_query, callback_data, AsyncMock(), _admin_user())

    appointment_scheduler.resync_appointment_jobs.assert_awaited_once()
    resynced_appointment = appointment_scheduler.resync_appointment_jobs.call_args.args[0]
    assert resynced_appointment.status is AppointmentStatus.COMPLETED


@pytest.mark.asyncio
async def test_skip_edit_denies_access_to_other_doctors_appointment():
    appointment_repo = FakeAppointmentRepository(_appointment(doctor_id=1))
    router = _router(appointment_repo)
    skip_edit = _find_handler(router, "skip_edit")

    callback_query = _callback_query(telegram_user_id=OTHER_ADMIN_TELEGRAM_ID)
    callback_data = CompletionFollowupCB(action="skip", appointment_id=1)

    await skip_edit(callback_query, callback_data, AsyncMock(), _admin_user())

    callback_query.answer.assert_called_once_with("Запись не найдена.", show_alert=True)
    assert appointment_repo.appointment.status is AppointmentStatus.CONFIRMED
    assert appointment_repo.status_updates == []


def _name_search_state():
    return FSMContext(storage=MemoryStorage(), key=(ADMIN_TELEGRAM_ID, ADMIN_TELEGRAM_ID))


@pytest.mark.asyncio
async def test_skip_completion_clears_an_active_name_search_state():
    appointment_repo = FakeAppointmentRepository(_appointment())
    skip_edit = _find_handler(_router(appointment_repo), "skip_edit")
    callback_query = _callback_query()
    state = _name_search_state()
    await state.set_state(AppointmentBrowserStates.search_name)
    await state.update_data(full_name="Draft", card_message_id=111)

    await skip_edit(
        callback_query, CompletionFollowupCB(action="skip", appointment_id=1), state, _admin_user(),
    )

    assert await state.get_state() is None
    assert await state.get_data() == {}


@pytest.mark.asyncio
async def test_open_edit_clears_an_active_name_search_state_and_tracks_card():
    appointment_repo = FakeAppointmentRepository(_appointment())
    open_edit = _find_handler(_router(appointment_repo), "open_edit")
    callback_query = _callback_query()
    callback_query.message.chat.id = 333
    callback_query.message.message_id = 444
    state = _name_search_state()
    await state.set_state(AppointmentBrowserStates.search_name)
    await state.update_data(full_name="Draft", card_message_id=111)

    await open_edit(
        callback_query, CompletionFollowupCB(action="edit", appointment_id=1), state, _admin_user(),
    )

    assert await state.get_state() is None
    assert await state.get_data() == {"card_chat_id": 333, "card_message_id": 444}


@pytest.mark.asyncio
@pytest.mark.parametrize(("handler_name", "action"), [("open_edit", "edit"), ("skip_edit", "skip")])
async def test_completion_does_not_clear_name_search_state_when_already_decided(handler_name, action):
    appointment = _appointment()
    appointment.status = AppointmentStatus.COMPLETED
    handler = _find_handler(_router(FakeAppointmentRepository(appointment)), handler_name)
    callback_query = _callback_query()
    state = _name_search_state()
    await state.set_state(AppointmentBrowserStates.search_name)
    await state.update_data(full_name="Draft", card_message_id=111)

    await handler(
        callback_query, CompletionFollowupCB(action=action, appointment_id=1), state, _admin_user(),
    )

    assert await state.get_state() == AppointmentBrowserStates.search_name.state
    assert await state.get_data() == {"full_name": "Draft", "card_message_id": 111}


@pytest.mark.asyncio
async def test_skip_edit_shows_alert_and_does_not_finalize_when_already_decided():
    appointment = _appointment()
    appointment.status = AppointmentStatus.COMPLETED
    appointment_repo = FakeAppointmentRepository(appointment)
    notification_service = MagicMock()
    notification_service.invalidate_stale_decision_message = AsyncMock()
    router = _router(appointment_repo, notification_service=notification_service)
    skip_edit = _find_handler(router, "skip_edit")

    callback_query = _callback_query()
    callback_query.message.chat.id = 111
    callback_query.message.message_id = 222
    callback_data = CompletionFollowupCB(action="skip", appointment_id=1)

    await skip_edit(callback_query, callback_data, AsyncMock(), _admin_user())

    callback_query.answer.assert_called_once_with(ALREADY_DECIDED_ALERT, show_alert=True)
    callback_query.message.edit_text.assert_not_called()
    assert appointment_repo.status_updates == []
    notification_service.invalidate_stale_decision_message.assert_awaited_once_with(
        111, 222,
        {"ru": "Другой сотрудник", "uz": "Boshqa xodim"},
        {"ru": "приём завершён", "uz": "qabul yakunlandi"},
        appointment_summary="Запись №1\nВремя: 10.07.2026 10:00\nУслуга: Консультация\nСтатус: ✔️ завершена",
    )


@pytest.mark.parametrize(("lang", "label"), [("ru", "Подробнее"), ("uz", "Batafsil")])
def test_completion_sibling_details_keyboard_contains_only_ids(lang, label):
    markup = completion_sibling_details_kb(188, 41, lang)
    callback = CompletionSiblingDetailsCB.unpack(markup.inline_keyboard[0][0].callback_data)

    assert markup.inline_keyboard[0][0].text == label
    assert callback.model_dump() == {"appointment_id": 188, "actor_user_id": 41}


@pytest.mark.parametrize(("lang", "label"), [("ru", "Скрыть"), ("uz", "Yopish")])
def test_completion_sibling_hide_keyboard_contains_only_ids(lang, label):
    markup = completion_sibling_hide_details_kb(188, 41, lang)
    callback = CompletionSiblingHideDetailsCB.unpack(markup.inline_keyboard[0][0].callback_data)

    assert markup.inline_keyboard[0][0].text == label
    assert callback.model_dump() == {"appointment_id": 188, "actor_user_id": 41}


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("ru", "Приём №188 завершён.\nЗавершил(а): Доктор Анна"),
        ("uz", "№188 qabul yakunlandi.\nYakunladi: Doktor Anna"),
    ],
)
def test_staff_completion_result_text_is_localized(lang, expected):
    assert staff_completion_result_text(188, "Доктор Анна" if lang == "ru" else "Doktor Anna", lang) == expected


def _completed_appointment():
    appointment = _appointment()
    appointment.status = AppointmentStatus.COMPLETED
    appointment.decided_by_user_id = 1
    return appointment


@pytest.mark.asyncio
async def test_completion_sibling_details_shows_authorized_appointment_card():
    appointment_repo = FakeAppointmentRepository(_completed_appointment())
    handler = _find_handler(_router(appointment_repo), "show_completion_sibling_details")
    callback_query = _callback_query()

    await handler(callback_query, CompletionSiblingDetailsCB(appointment_id=1, actor_user_id=1), _admin_user())

    callback_query.answer.assert_awaited_once_with("")
    callback_query.message.edit_text.assert_awaited_once_with(
        build_appointment_card(appointment_repo.appointment, "ru"),
        reply_markup=completion_sibling_hide_details_kb(1, 1, "ru"),
    )


@pytest.mark.asyncio
async def test_completion_sibling_hide_restores_compact_actor_result():
    appointment_repo = FakeAppointmentRepository(_completed_appointment())
    handler = _find_handler(_router(appointment_repo), "hide_completion_sibling_details")
    callback_query = _callback_query()

    await handler(callback_query, CompletionSiblingHideDetailsCB(appointment_id=1, actor_user_id=1), _admin_user())

    callback_query.answer.assert_awaited_once_with("")
    callback_query.message.edit_text.assert_awaited_once_with(
        "Приём №1 завершён.\nЗавершил(а): Доктор Петров Петр",
        reply_markup=completion_sibling_details_kb(1, 1, "ru"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "callback_data"),
    [
        ("show_completion_sibling_details", CompletionSiblingDetailsCB(appointment_id=1, actor_user_id=2)),
        ("hide_completion_sibling_details", CompletionSiblingHideDetailsCB(appointment_id=1, actor_user_id=2)),
    ],
)
async def test_completion_sibling_callbacks_reject_forged_actor_id(handler_name, callback_data):
    handler = _find_handler(_router(FakeAppointmentRepository(_completed_appointment())), handler_name)
    callback_query = _callback_query()

    await handler(callback_query, callback_data, _admin_user())

    callback_query.answer.assert_awaited_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "callback_data"),
    [
        ("show_completion_sibling_details", CompletionSiblingDetailsCB(appointment_id=1, actor_user_id=1)),
        ("hide_completion_sibling_details", CompletionSiblingHideDetailsCB(appointment_id=1, actor_user_id=1)),
    ],
)
async def test_completion_sibling_callbacks_reject_out_of_scope_appointment(handler_name, callback_data):
    appointment = _completed_appointment()
    handler = _find_handler(_router(FakeAppointmentRepository(appointment)), handler_name)
    callback_query = _callback_query(OTHER_ADMIN_TELEGRAM_ID)

    await handler(callback_query, callback_data, _admin_user())

    callback_query.answer.assert_awaited_once_with("Запись не найдена.", show_alert=True)
    callback_query.message.edit_text.assert_not_called()


@pytest.mark.asyncio
async def test_skip_edit_replaces_sibling_before_actor_edit_failure():
    appointment_repo = FakeAppointmentRepository(
        _appointment(),
        notifications=[AppointmentNotification(appointment_id=1, chat_id=555, message_id=777, kind="completion")],
    )
    notification_service = MagicMock()
    notification_service.resolve_recipient_language = AsyncMock(return_value="ru")
    notification_service.notifier.try_edit_message_text = AsyncMock()
    handler = _find_handler(_router(appointment_repo, notification_service=notification_service), "skip_edit")
    callback_query = _callback_query()
    callback_query.message.edit_text.side_effect = RuntimeError("telegram unavailable")

    with pytest.raises(RuntimeError, match="telegram unavailable"):
        await handler(callback_query, CompletionFollowupCB(action="skip", appointment_id=1), AsyncMock(), _admin_user())

    notification_service.notifier.try_edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_open_edit_does_not_replace_the_actor_completion_prompt():
    appointment_repo = FakeAppointmentRepository(
        _appointment(),
        notifications=[AppointmentNotification(appointment_id=1, chat_id=ADMIN_TELEGRAM_ID, message_id=777, kind="completion")],
    )
    notification_service = MagicMock()
    notification_service.resolve_recipient_language = AsyncMock(return_value="ru")
    notification_service.notifier.try_edit_message_text = AsyncMock()
    handler = _find_handler(_router(appointment_repo, notification_service=notification_service), "open_edit")

    await handler(_callback_query(), CompletionFollowupCB(action="edit", appointment_id=1), AsyncMock(), _admin_user())

    notification_service.notifier.try_edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_open_edit_replaces_sibling_before_actor_callback_answer_failure():
    appointment_repo = FakeAppointmentRepository(
        _appointment(),
        notifications=[AppointmentNotification(appointment_id=1, chat_id=555, message_id=777, kind="completion")],
    )
    notification_service = MagicMock()
    notification_service.resolve_recipient_language = AsyncMock(return_value="ru")
    notification_service.notifier.try_edit_message_text = AsyncMock()
    handler = _find_handler(_router(appointment_repo, notification_service=notification_service), "open_edit")
    callback_query = _callback_query()
    callback_query.answer.side_effect = RuntimeError("callback answer unavailable")

    with pytest.raises(RuntimeError, match="callback answer unavailable"):
        await handler(callback_query, CompletionFollowupCB(action="edit", appointment_id=1), AsyncMock(), _admin_user())

    notification_service.notifier.try_edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("first_result", [RuntimeError("first edit failed"), False])
async def test_completion_sibling_replacement_continues_after_failed_first_edit(first_result):
    notification_service = MagicMock()
    notification_service.resolve_recipient_language = AsyncMock(side_effect=["ru", "uz"])
    notification_service.notifier.try_edit_message_text = AsyncMock(side_effect=[first_result, True])
    appt_mng = MagicMock()
    appt_mng.resolve_decision_label = AsyncMock(return_value={"ru": "Доктор Анна", "uz": "Doktor Anna"})
    appt_mng.get_invalidation_targets = AsyncMock(return_value=[
        AppointmentNotification(appointment_id=1, chat_id=555, message_id=777, kind="completion"),
        AppointmentNotification(appointment_id=1, chat_id=556, message_id=778, kind="completion"),
    ])
    appointment = _completed_appointment()

    await replace_completion_sibling_prompts(notification_service, appt_mng, appointment, ADMIN_TELEGRAM_ID)

    assert notification_service.notifier.try_edit_message_text.await_count == 2
