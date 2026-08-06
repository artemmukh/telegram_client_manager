"""Unit coverage for the shared no-slots alert helper
(bot/handlers/utils/appointment_slot_helpers.py::answer_no_slots_for_day),
extracted from the admin and client "no slots for day" branches.

Regression target: before this helper existed, each of the three call sites
(admin_utils/appointment_helpers.py, client appointment_booking.py, client
appointment_reschedule.py) called get_day_block_reason + callback_query.answer
inline -- the refactor must not change the observable alert text, and the two
"generic no slots" wordings (admin vs client) must stay distinct.
"""
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.utils.appointment_slot_helpers import answer_no_slots_for_day


class _FakeApptMng:
    def __init__(self, reason=None):
        self.reason = reason
        self.calls = []

    async def get_day_block_reason(self, doctor_id, day, now):
        self.calls.append((doctor_id, day, now))
        return self.reason


def _callback_query():
    callback_query = MagicMock()
    callback_query.answer = AsyncMock()
    return callback_query


@pytest.mark.asyncio
async def test_answer_no_slots_for_day_shows_generic_text_without_a_block():
    appt_mng = _FakeApptMng(reason=None)
    callback_query = _callback_query()

    await answer_no_slots_for_day(
        appt_mng, callback_query, doctor_id=42, day=date(2026, 7, 20),
        now=datetime(2026, 7, 1, 9, 0), no_slots_text="custom no-slots text", lang="ru",
    )

    callback_query.answer.assert_awaited_once_with("custom no-slots text", show_alert=True)
    assert appt_mng.calls == [(42, date(2026, 7, 20), datetime(2026, 7, 1, 9, 0))]


@pytest.mark.asyncio
async def test_answer_no_slots_for_day_shows_block_reason_when_day_is_blocked():
    appt_mng = _FakeApptMng(reason="Отпуск врача")
    callback_query = _callback_query()

    await answer_no_slots_for_day(
        appt_mng, callback_query, doctor_id=42, day=date(2026, 7, 20),
        now=datetime(2026, 7, 1, 9, 0), no_slots_text="custom no-slots text", lang="ru",
    )

    toast_text = callback_query.answer.call_args.args[0]
    assert "Отпуск врача" in toast_text
    assert "custom no-slots text" not in toast_text
    assert callback_query.answer.call_args.kwargs == {"show_alert": True}


@pytest.mark.asyncio
async def test_answer_no_slots_for_day_does_not_escape_a_reason_with_html_special_characters():
    """callback_query.answer(show_alert=True) has no parse_mode -- a reason
    with '<' must reach it verbatim, or Telegram would show the literal
    '&lt;' entity to the user instead of the intended character."""
    appt_mng = _FakeApptMng(reason="Ремонт <кабинет>")
    callback_query = _callback_query()

    await answer_no_slots_for_day(
        appt_mng, callback_query, doctor_id=42, day=date(2026, 7, 20),
        now=datetime(2026, 7, 1, 9, 0), no_slots_text="custom no-slots text", lang="ru",
    )

    toast_text = callback_query.answer.call_args.args[0]
    assert "<кабинет>" in toast_text
    assert "&lt;" not in toast_text
