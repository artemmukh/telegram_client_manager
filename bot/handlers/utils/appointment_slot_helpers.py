from datetime import date, datetime

from aiogram.types import CallbackQuery

import bot.messages.booking as msg


async def answer_no_slots_for_day(
    appt_mng, callback_query: CallbackQuery, doctor_id: int, day: date, now: datetime, no_slots_text: str,
    lang: str = "ru",
) -> None:
    """Alert for a day whose slot grid came back empty: the blocking reason when
    a block covers the day's slots, `no_slots_text` otherwise.

    `now` must be the same value used to build the (empty) grid, so both calls
    agree on which slots exist for the day.

    Shared by the admin and client booking/reschedule flows, which each have
    their own wording for the generic no-slots case -- callers pass their own
    already-localized `no_slots_text` instead of this helper picking one."""
    reason = await appt_mng.get_day_block_reason(doctor_id, day, now)

    if reason is not None:
        await callback_query.answer(msg.day_blocked(reason, lang), show_alert=True)
        return

    await callback_query.answer(no_slots_text, show_alert=True)
