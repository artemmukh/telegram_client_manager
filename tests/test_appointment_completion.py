"""Tests for the post-appointment follow-up handlers (Да/Нет prompt).

"Да" opens the same appointment card in the post-appointment editing window
(status stays CONFIRMED). "Нет" finalizes the appointment as COMPLETED
immediately, since the auto-completion job no longer does this itself.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.admin.appointment_management.appointment_completion import (
    create_admin_completion_router,
)
from bot.keyboards.admin.record_management_kb.completion_followup_cb import CompletionFollowupCB
from bot.models.appointment import Appointment
from bot.utils.appointment_enums import AppointmentStatus, CreatedBy


class FakeAppointmentRepository:
    def __init__(self, appointment):
        self.appointment = appointment
        self.status_updates = []

    async def get_appointment_by_id(self, appointment_id):
        return self.appointment

    async def update_appointment_status(self, appointment_id, status, status_updated_at):
        self.appointment.status = status
        self.status_updates.append((appointment_id, status))


def _find_handler(router, name):
    for handler in router.callback_query.handlers:
        if handler.callback.__name__ == name:
            return handler.callback
    raise AssertionError(f"handler {name} not found")


def _appointment():
    return Appointment(
        clinic_id=1,
        client_id=1,
        datetime="2026-07-10 10:00",
        purpose="Консультация",
        created_by=CreatedBy.ADMIN,
        status=AppointmentStatus.CONFIRMED,
        id=1,
    )


def _callback_query():
    callback_query = MagicMock()
    callback_query.answer = AsyncMock()
    callback_query.message.edit_text = AsyncMock()
    return callback_query


@pytest.mark.asyncio
async def test_open_edit_keeps_status_confirmed_and_renders_post_appt_card():
    appointment_repo = FakeAppointmentRepository(_appointment())
    router = create_admin_completion_router(appointment_repo, MagicMock(), MagicMock(), MagicMock())
    open_edit = _find_handler(router, "open_edit")

    callback_query = _callback_query()
    callback_data = CompletionFollowupCB(action="edit", appointment_id=1)

    await open_edit(callback_query, callback_data, AsyncMock())

    assert appointment_repo.appointment.status is AppointmentStatus.CONFIRMED
    assert appointment_repo.status_updates == []

    reply_markup = callback_query.message.edit_text.call_args.kwargs["reply_markup"]
    callback_datas = [button.callback_data for row in reply_markup.inline_keyboard for button in row]
    assert any("finish_appointment" in cb for cb in callback_datas)


@pytest.mark.asyncio
async def test_skip_edit_finalizes_status_as_completed():
    appointment_repo = FakeAppointmentRepository(_appointment())
    router = create_admin_completion_router(appointment_repo, MagicMock(), MagicMock(), MagicMock())
    skip_edit = _find_handler(router, "skip_edit")

    callback_query = _callback_query()
    callback_data = CompletionFollowupCB(action="skip", appointment_id=1)

    await skip_edit(callback_query, callback_data)

    assert appointment_repo.appointment.status is AppointmentStatus.COMPLETED
    assert appointment_repo.status_updates == [(1, AppointmentStatus.COMPLETED)]
    callback_query.message.edit_text.assert_called_once_with("Приём завершён.", reply_markup=None)
