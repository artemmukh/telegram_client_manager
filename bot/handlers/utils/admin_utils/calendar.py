



from aiogram.types import CallbackQuery , Message
from aiogram.fsm.context import FSMContext

from bot.handlers.utils.admin_utils.appointment_calendar_helpers import clamp_month_to_range, format_month_label
from bot.handlers.utils.admin_utils.client_browser_helpers import remember_tracked_message
from bot.keyboards.admin.record_management_kb.appointment_browser_kb import appointment_calendar_kb
from bot.services.utils.date_parser import get_current_tashkent_datetime
from bot.states.admin.record_management.appointment_browser_states import AppointmentBrowserStates


async def show_calendar(
    event: CallbackQuery | Message,
    state: FSMContext,
):
    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
    else:
        message = event

    await state.clear()

    today = get_current_tashkent_datetime().date()
    year, month = clamp_month_to_range(today.year, today.month)

    await state.update_data(
        calendar_year=year,
        calendar_month=month,
    )
    await state.set_state(AppointmentBrowserStates.calendar_month)

    if isinstance(event, CallbackQuery):
        await message.edit_text(
            f"📅 {format_month_label(year, month)}",
            reply_markup=appointment_calendar_kb(year, month),
        )
        await remember_tracked_message(state, message)
    else:
        sent = await message.answer(
            f"📅 {format_month_label(year, month)}",
            reply_markup=appointment_calendar_kb(year, month),
        )
        await remember_tracked_message(state, sent)