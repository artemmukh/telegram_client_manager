



from aiogram.types import CallbackQuery , Message
from aiogram.fsm.context import FSMContext

from bot.handlers.utils.admin_utils.appointment_calendar_helpers import (
    calendar_grid_back_target,
    clamp_month_to_range,
    format_month_label,
)
from bot.handlers.utils.admin_utils.client_browser_helpers import remember_tracked_message
from bot.keyboards.admin.record_management_kb.appointment_browser_kb import appointment_calendar_kb
from bot.services.utils.date_parser import get_current_tashkent_datetime
from bot.states.admin.record_management.appointment_browser_states import AppointmentBrowserStates


async def show_calendar(
    event: CallbackQuery | Message,
    state: FSMContext,
    lang: str = "ru",
):
    if isinstance(event, CallbackQuery):
        await event.answer()
        message = event.message
    else:
        message = event

    today = get_current_tashkent_datetime().date()
    year, month = clamp_month_to_range(today.year, today.month)

    data = await state.update_data(
        calendar_year=year,
        calendar_month=month,
    )
    await state.set_state(AppointmentBrowserStates.calendar_month)

    back_callback_data, back_label = calendar_grid_back_target(data, lang)

    if isinstance(event, CallbackQuery):
        await event.answer('')
        message = event.message
        await message.edit_text(
            f"📅 {format_month_label(year, month, lang)}",
            reply_markup=appointment_calendar_kb(
                year, month, back_callback_data=back_callback_data, back_label=back_label, lang=lang,
            ),
        )
        await remember_tracked_message(state, message)
    else:
        message = event
        sent = await message.answer(
            f"📅 {format_month_label(year, month, lang)}",
            reply_markup=appointment_calendar_kb(
                year, month, back_callback_data=back_callback_data, back_label=back_label, lang=lang,
            ),
        )
        await remember_tracked_message(state, sent)