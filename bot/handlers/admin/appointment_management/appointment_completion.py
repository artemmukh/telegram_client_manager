import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.exceptions.appointment_exceptions import AppointmentAlreadyDecidedError
from bot.exceptions.exceptions import BotException
from bot.handlers.utils.admin_utils.appointment_browser_helpers import (
    remember_tracked_message,
)
from bot.handlers.utils.admin_utils.appointment_decision_helpers import (
    invalidate_actor_stale_message,
    replace_completion_sibling_prompts,
    staff_completion_result_text,
)
from bot.handlers.utils.admin_utils.appointment_helpers import build_appointment_card
from bot.keyboards.admin.record_management_kb.appointment_browser_kb import (
    appointment_card_kb,
)
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
from bot.models.user import User
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.utils.role import RoleFilter

logger = logging.getLogger(__name__)

_APPOINTMENT_NOT_FOUND = {
    "ru": "Запись не найдена.",
    "uz": "Yozuv topilmadi.",
}

_ALREADY_AUTO_COMPLETED = {
    "ru": "Запись уже автозавершена, вы можете скорректировать её в «Завершённые»",
    "uz": "Yozuv allaqachon avtoyakunlangan, uni «Yakunlangan»da tuzatishingiz mumkin",
}

_APPOINTMENT_COMPLETED = {
    "ru": "Приём завершён.",
    "uz": "Qabul yakunlandi.",
}


def create_admin_completion_router(
    appointment_repo, user_repo, staff_repo, clinic_repo, appointment_scheduler=None, notification_service=None,
) -> Router:
    router = Router()
    router.callback_query.filter(RoleFilter("admin"))

    appt_mng = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

    @router.callback_query(CompletionFollowupCB.filter(F.action == "edit"))
    async def open_edit(
        callback_query: CallbackQuery, callback_data: CompletionFollowupCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
            return

        try:
            appointment = await appt_mng.complete_appointment_by_admin(owned_appointment, callback_query.from_user.id)
        except AppointmentAlreadyDecidedError as e:
            await callback_query.answer(
                _ALREADY_AUTO_COMPLETED.get(lang, _ALREADY_AUTO_COMPLETED["ru"]), show_alert=True,
            )
            if notification_service:
                try:
                    await invalidate_actor_stale_message(
                        notification_service, e,
                        callback_query.message.chat.id, callback_query.message.message_id, lang,
                    )
                except Exception as invalidation_error:
                    logger.warning(
                        f"Failed to invalidate own stale completion message for appointment "
                        f"{callback_data.appointment_id}: {invalidation_error}"
                    )
            return
        except BotException as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
            return

        if notification_service:
            await replace_completion_sibling_prompts(
                notification_service, appt_mng, appointment, callback_query.from_user.id,
            )

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

        await state.clear()
        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_appointment_card(appointment, lang),
            reply_markup=appointment_card_kb(
                appointment.id, mode="list", page=1, status=appointment.status, tab="completed", post_appt=True,
                lang=lang,
            ),
        )
        await remember_tracked_message(state, callback_query.message)

    @router.callback_query(CompletionFollowupCB.filter(F.action == "skip"))
    async def skip_edit(
        callback_query: CallbackQuery, callback_data: CompletionFollowupCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        owned_appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if owned_appointment is None:
            await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
            return

        try:
            appointment = await appt_mng.complete_appointment_by_admin(owned_appointment, callback_query.from_user.id)
        except AppointmentAlreadyDecidedError as e:
            await callback_query.answer(
                _ALREADY_AUTO_COMPLETED.get(lang, _ALREADY_AUTO_COMPLETED["ru"]), show_alert=True,
            )
            if notification_service:
                try:
                    await invalidate_actor_stale_message(
                        notification_service, e,
                        callback_query.message.chat.id, callback_query.message.message_id, lang,
                    )
                except Exception as invalidation_error:
                    logger.warning(
                        f"Failed to invalidate own stale completion message for appointment "
                        f"{callback_data.appointment_id}: {invalidation_error}"
                    )
            return
        except BotException as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
            return

        if notification_service:
            await replace_completion_sibling_prompts(
                notification_service, appt_mng, appointment, callback_query.from_user.id,
            )

        if appointment_scheduler:
            await appointment_scheduler.resync_appointment_jobs(appointment)

        await state.clear()
        await callback_query.answer('')
        await callback_query.message.edit_text(
            _APPOINTMENT_COMPLETED.get(lang, _APPOINTMENT_COMPLETED["ru"]),
            reply_markup=completion_details_kb(appointment.id, lang),
        )

    @router.callback_query(CompletionSiblingDetailsCB.filter())
    async def show_completion_sibling_details(
        callback_query: CallbackQuery, callback_data: CompletionSiblingDetailsCB, current_user: User,
    ):
        lang = current_user.language
        appointment = await appt_mng.get_completion_sibling_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id, callback_data.actor_user_id,
        )
        if appointment is None:
            await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
            return

        await callback_query.answer("")
        await callback_query.message.edit_text(
            build_appointment_card(appointment, lang),
            reply_markup=completion_sibling_hide_details_kb(
                appointment.id, callback_data.actor_user_id, lang,
            ),
        )

    @router.callback_query(CompletionSiblingHideDetailsCB.filter())
    async def hide_completion_sibling_details(
        callback_query: CallbackQuery, callback_data: CompletionSiblingHideDetailsCB, current_user: User,
    ):
        lang = current_user.language
        appointment = await appt_mng.get_completion_sibling_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id, callback_data.actor_user_id,
        )
        if appointment is None:
            await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
            return

        actor_label = await appt_mng.resolve_decision_label(appointment.decided_by_user_id)
        await callback_query.answer("")
        await callback_query.message.edit_text(
            staff_completion_result_text(
                appointment.id, actor_label.get(lang, actor_label["ru"]), lang,
            ),
            reply_markup=completion_sibling_details_kb(
                appointment.id, callback_data.actor_user_id, lang,
            ),
        )

    @router.callback_query(CompletionDetailsCB.filter())
    async def show_completion_details(
        callback_query: CallbackQuery, callback_data: CompletionDetailsCB, current_user: User,
    ):
        lang = current_user.language
        appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if appointment is None:
            await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_appointment_card(appointment, lang),
            reply_markup=completion_hide_details_kb(appointment.id, lang),
        )

    @router.callback_query(CompletionHideDetailsCB.filter())
    async def hide_completion_details(
        callback_query: CallbackQuery, callback_data: CompletionHideDetailsCB, current_user: User,
    ):
        lang = current_user.language
        appointment = await appt_mng.get_appointment_for_admin(
            callback_data.appointment_id, callback_query.from_user.id
        )
        if appointment is None:
            await callback_query.answer(_APPOINTMENT_NOT_FOUND.get(lang, _APPOINTMENT_NOT_FOUND["ru"]), show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            _APPOINTMENT_COMPLETED.get(lang, _APPOINTMENT_COMPLETED["ru"]),
            reply_markup=completion_details_kb(appointment.id, lang),
        )

    return router
