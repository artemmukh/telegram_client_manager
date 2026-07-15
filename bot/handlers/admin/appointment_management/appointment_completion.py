from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.exceptions.exceptions import BotException
from bot.handlers.utils.admin_utils.appointment_browser_helpers import remember_tracked_message
from bot.handlers.utils.admin_utils.appointment_helpers import build_appointment_card
from bot.keyboards.admin.record_management_kb.appointment_browser_kb import appointment_card_kb
from bot.keyboards.admin.record_management_kb.completion_followup_cb import CompletionFollowupCB
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.utils.appointment_enums import AppointmentStatus
from bot.utils.role import RoleFilter


def create_admin_completion_router(appointment_repo, user_repo, staff_repo, clinic_repo) -> Router:
    router = Router()
    router.callback_query.filter(RoleFilter("admin"))

    appt_mng = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

    @router.callback_query(CompletionFollowupCB.filter(F.action == "edit"))
    async def open_edit(callback_query: CallbackQuery, callback_data: CompletionFollowupCB, state: FSMContext):
        appointment = await appt_mng.get_appointment_for_admin(callback_data.appointment_id, callback_query.from_user.id)
        if appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_appointment_card(appointment),
            reply_markup=appointment_card_kb(
                appointment.id, mode="list", page=1, status=appointment.status, tab="completed", post_appt=True,
            ),
        )
        await remember_tracked_message(state, callback_query.message)

    @router.callback_query(CompletionFollowupCB.filter(F.action == "skip"))
    async def skip_edit(callback_query: CallbackQuery, callback_data: CompletionFollowupCB):
        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer("Запись не найдена.", show_alert=True)
            return

        try:
            await appt_mng.update_status(callback_data.appointment_id, AppointmentStatus.COMPLETED)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text("Приём завершён.", reply_markup=None)

    return router
