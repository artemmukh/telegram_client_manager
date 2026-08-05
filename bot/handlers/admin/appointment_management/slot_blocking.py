import logging
from math import ceil

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.blocked_slot_exceptions import InvalidBlockRangeError
from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import UserNotFoundError
from bot.handlers.utils.admin_utils.appointment_decision_helpers import notify_staff_appointment_cancellation
from bot.keyboards.admin.record_management_kb.appointment_kb import back_to_records_kb
from bot.keyboards.admin.record_management_kb.slot_blocking_cb import (
    SlotBlockCancelCB,
    SlotBlockConfirmCB,
    SlotBlockListCB,
    SlotBlockTargetCB,
)
from bot.keyboards.admin.record_management_kb.slot_blocking_kb import (
    slot_blocking_cancel_confirm_kb,
    slot_blocking_confirm_kb,
    slot_blocking_list_kb,
    slot_blocking_menu_kb,
    slot_blocking_target_kb,
)
from bot.models.user import User
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.appointment.slot_blocking import SlotBlockingService
from bot.services.utils.date_parser import format_appointment_card_datetime
from bot.states.admin.record_management.slot_blocking_states import SlotBlockCreationStates
from bot.utils.role import RoleFilter

logger = logging.getLogger(__name__)

_BLOCKS_PER_PAGE = 10

_MENU_TEXT = {
    "ru": "🚫 Блокировка слотов",
    "uz": "🚫 Slotlarni bloklash",
}
_CHOOSE_TARGET_TEXT = {
    "ru": "Для какого врача заблокировать время?",
    "uz": "Qaysi shifokor uchun vaqt bloklansin?",
}
_ASK_RANGE_START_TEXT = {
    "ru": "Введите начало блокировки (дд.мм.гггг чч.мм):",
    "uz": "Bloklash boshlanishini kiriting (kk.oo.yyyy ss.mm):",
}
_ASK_RANGE_END_TEXT = {
    "ru": "Введите окончание блокировки (дд.мм.гггг чч.мм):",
    "uz": "Bloklash tugashini kiriting (kk.oo.yyyy ss.mm):",
}
_ASK_REASON_TEXT = {
    "ru": "Укажите причину блокировки:",
    "uz": "Bloklash sababini kiriting:",
}
_CONFLICTS_HEADER_TEXT = {
    "ru": "⚠️ На это время уже есть записи, они будут отменены:\n\n",
    "uz": "⚠️ Bu vaqtga allaqachon yozuvlar mavjud, ular bekor qilinadi:\n\n",
}
_CONFLICTS_FOOTER_TEXT = {
    "ru": "\nПродолжить создание блокировки?",
    "uz": "\nBloklashni yaratishni davom ettirasizmi?",
}
_CONFLICT_LINE_TEXT = {
    "ru": "• {datetime} — {client}",
    "uz": "• {datetime} — {client}",
}
_UNKNOWN_CLIENT_LABEL = {
    "ru": "клиент не указан",
    "uz": "mijoz korsatilmagan",
}
_CONFIRM_BLOCK_TEXT = {
    "ru": "Создать блокировку с {start} по {end}?\nПричина: {reason}",
    "uz": "{start} dan {end} gacha bloklash yaratilsinmi?\nSabab: {reason}",
}
_BLOCK_CREATED_TEXT = {
    "ru": "✅ Блокировка создана.",
    "uz": "✅ Bloklash yaratildi.",
}
_INVALID_RANGE_RETRY_TEXT = {
    "ru": "\n\nВведите начало блокировки заново (дд.мм.гггг чч.мм):",
    "uz": "\n\nBloklash boshlanishini qaytadan kiriting (kk.oo.yyyy ss.mm):",
}
_LIST_HEADER_TEXT = {
    "ru": "📒 Активные блокировки ({current}/{total})",
    "uz": "📒 Faol bloklashlar ({current}/{total})",
}
_LIST_EMPTY_TEXT = {
    "ru": "Активных блокировок нет.",
    "uz": "Faol bloklashlar yoq.",
}
_BLOCK_LINE_TEXT = {
    "ru": "🚫 №{id} | {start} — {end}\n👤 {target}\n📝 {reason}",
    "uz": "🚫 №{id} | {start} — {end}\n👤 {target}\n📝 {reason}",
}
_CLINIC_WIDE_TARGET_LABEL = {
    "ru": "Вся клиника",
    "uz": "Butun klinika",
}
_UNKNOWN_DOCTOR_LABEL = {
    "ru": "Врач не найден",
    "uz": "Shifokor topilmadi",
}
_CANCEL_CONFIRM_PROMPT_TEXT = {
    "ru": "⚠️ Отменить блокировку №{id}?\nРанее отменённые из-за неё записи НЕ восстановятся.",
    "uz": "⚠️ №{id} bloklash bekor qilinsinmi?\nBu tufayli bekor qilingan yozuvlar TIKLANMAYDI.",
}
_CANCEL_SUCCESS_ANSWER_TEXT = {
    "ru": "Блокировка отменена",
    "uz": "Bloklash bekor qilindi",
}
_BLOCK_UNAVAILABLE_TEXT = {
    "ru": "Блокировка не найдена.",
    "uz": "Bloklash topilmadi.",
}


def create_admin_slot_blocking_router(
    user_repository, staff_repository, clinic_repository, appointment_repository, blocked_slot_repository,
    notification_service=None, appointment_scheduler=None,
):
    router = Router()

    appt_mng = AppointmentManagement(appointment_repository, user_repository, staff_repository, clinic_repository)
    slot_blocking_service = SlotBlockingService(
        blocked_slot_repository, appointment_repository, user_repository, staff_repository, clinic_repository,
    )

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    async def resolve_scope(callback_query: CallbackQuery, lang: str) -> tuple[int, int | None] | None:
        try:
            return await appt_mng.resolve_admin_appointment_filter(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
            return None

    async def ask_range_start(callback_query: CallbackQuery, state: FSMContext, lang: str) -> None:
        await state.set_state(SlotBlockCreationStates.range_start)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            _ASK_RANGE_START_TEXT.get(lang, _ASK_RANGE_START_TEXT["ru"]),
            reply_markup=back_to_records_kb(lang=lang),
        )

    @router.callback_query(F.data == "slot_blocking_menu")
    async def open_menu(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        await state.clear()
        await callback_query.answer('')
        await callback_query.message.edit_text(
            _MENU_TEXT.get(lang, _MENU_TEXT["ru"]), reply_markup=slot_blocking_menu_kb(lang=lang),
        )

    @router.callback_query(F.data == "slot_blocking_create")
    async def start_create(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        await state.clear()

        scope = await resolve_scope(callback_query, lang)
        if scope is None:
            return
        clinic_id, doctor_id = scope

        await state.update_data(clinic_id=clinic_id)

        if doctor_id is not None:
            await state.update_data(staff_id=doctor_id)
            await ask_range_start(callback_query, state, lang)
            return

        doctors = await appt_mng.list_clinic_doctors(clinic_id)
        await state.set_state(SlotBlockCreationStates.choose_target)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            _CHOOSE_TARGET_TEXT.get(lang, _CHOOSE_TARGET_TEXT["ru"]),
            reply_markup=slot_blocking_target_kb(doctors, lang=lang),
        )

    @router.callback_query(SlotBlockCreationStates.choose_target, SlotBlockTargetCB.filter())
    async def pick_target(
        callback_query: CallbackQuery, callback_data: SlotBlockTargetCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        await state.update_data(staff_id=callback_data.staff_id or None)
        await ask_range_start(callback_query, state, lang)

    @router.message(SlotBlockCreationStates.range_start, F.text)
    async def get_range_start(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        await state.update_data(range_start_raw=message.text.strip())
        await state.set_state(SlotBlockCreationStates.range_end)
        await message.answer(
            _ASK_RANGE_END_TEXT.get(lang, _ASK_RANGE_END_TEXT["ru"]), reply_markup=back_to_records_kb(lang=lang),
        )

    @router.message(SlotBlockCreationStates.range_end, F.text)
    async def get_range_end(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        data = await state.get_data()
        range_end_raw = message.text.strip()

        try:
            start, end = await slot_blocking_service.validate_range(data["range_start_raw"], range_end_raw)
        except InvalidBlockRangeError as e:
            await state.set_state(SlotBlockCreationStates.range_start)
            await message.answer(
                e.localized(lang) + _INVALID_RANGE_RETRY_TEXT.get(lang, _INVALID_RANGE_RETRY_TEXT["ru"]),
                reply_markup=back_to_records_kb(lang=lang),
            )
            return

        await state.update_data(
            range_start_raw=data["range_start_raw"], range_end_raw=range_end_raw,
            range_start=start, range_end=end,
        )
        await state.set_state(SlotBlockCreationStates.reason)
        await message.answer(
            _ASK_REASON_TEXT.get(lang, _ASK_REASON_TEXT["ru"]), reply_markup=back_to_records_kb(lang=lang),
        )

    @router.message(SlotBlockCreationStates.reason, F.text)
    async def get_reason(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        reason = message.text.strip()
        await state.update_data(reason=reason)
        data = await state.get_data()

        cancelable_conflicts = await slot_blocking_service.find_cancelable_conflicts(
            data["clinic_id"], data.get("staff_id"), data["range_start"], data["range_end"],
        )

        if cancelable_conflicts:
            lines = [
                _CONFLICT_LINE_TEXT.get(lang, _CONFLICT_LINE_TEXT["ru"]).format(
                    datetime=format_appointment_card_datetime(appointment.datetime),
                    client=appointment.client_full_name or _UNKNOWN_CLIENT_LABEL.get(lang, _UNKNOWN_CLIENT_LABEL["ru"]),
                )
                for appointment in cancelable_conflicts
            ]
            text = (
                _CONFLICTS_HEADER_TEXT.get(lang, _CONFLICTS_HEADER_TEXT["ru"])
                + "\n".join(lines)
                + _CONFLICTS_FOOTER_TEXT.get(lang, _CONFLICTS_FOOTER_TEXT["ru"])
            )
            await state.set_state(SlotBlockCreationStates.confirm_conflicts)
            await message.answer(text, reply_markup=slot_blocking_confirm_kb(lang=lang, has_conflicts=True))
            return

        await state.set_state(SlotBlockCreationStates.confirm_block)
        await message.answer(
            _CONFIRM_BLOCK_TEXT.get(lang, _CONFIRM_BLOCK_TEXT["ru"]).format(
                start=format_appointment_card_datetime(data["range_start"]),
                end=format_appointment_card_datetime(data["range_end"]),
                reason=reason,
            ),
            reply_markup=slot_blocking_confirm_kb(lang=lang, has_conflicts=False),
        )

    @router.callback_query(
        StateFilter(SlotBlockCreationStates.confirm_conflicts, SlotBlockCreationStates.confirm_block),
        SlotBlockConfirmCB.filter(),
    )
    async def confirm_block_creation(
        callback_query: CallbackQuery, callback_data: SlotBlockConfirmCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language

        if callback_data.action != "create":
            await state.clear()
            await callback_query.answer('')
            await callback_query.message.edit_text(
                _MENU_TEXT.get(lang, _MENU_TEXT["ru"]), reply_markup=slot_blocking_menu_kb(lang=lang),
            )
            return

        data = await state.get_data()

        try:
            block, cancelled_appointments = await slot_blocking_service.create_block(
                callback_query.from_user.id, data["clinic_id"], data.get("staff_id"),
                data["range_start_raw"], data["range_end_raw"], data["reason"],
            )
        except (InvalidBlockRangeError, UserNotFoundError) as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
            await state.clear()
            return
        except BotException as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
            await state.clear()
            return

        for appointment in cancelled_appointments:
            try:
                if notification_service:
                    await notification_service.notify_client_appointment_cancelled_by_admin(
                        appointment, reason=block.reason,
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to notify client about slot-block cancellation for appointment {appointment.id}: {e}"
                )
            try:
                await notify_staff_appointment_cancellation(
                    notification_service, appt_mng, callback_query.from_user.id, appointment, deleted=False,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to notify staff about slot-block cancellation for appointment {appointment.id}: {e}"
                )
            if appointment_scheduler:
                try:
                    await appointment_scheduler.cancel_all_jobs(appointment.id)
                except Exception as e:
                    logger.warning(
                        f"Failed to cancel scheduled jobs for slot-blocked appointment {appointment.id}: {e}"
                    )

        await callback_query.answer('')
        await callback_query.message.edit_text(
            _BLOCK_CREATED_TEXT.get(lang, _BLOCK_CREATED_TEXT["ru"]), reply_markup=back_to_records_kb(lang=lang),
        )
        await state.clear()

    async def render_blocks_list(
        callback_query: CallbackQuery, clinic_id: int, doctor_id: int | None, page: int, lang: str,
    ) -> None:
        blocks = await slot_blocking_service.list_active_blocks(clinic_id)
        if doctor_id is not None:
            # Own-scope doctor: only their own blocks (clinic-wide blocks are
            # created/managed by clinic-scope admins, not visible here).
            blocks = [block for block in blocks if block.staff_id == doctor_id]
        doctors = await appt_mng.list_clinic_doctors(clinic_id)
        doctor_name_by_id = {doctor.ID: doctor.full_name for doctor in doctors}

        total_pages = max(1, ceil(len(blocks) / _BLOCKS_PER_PAGE))
        page = min(max(page, 1), total_pages)
        start_index = (page - 1) * _BLOCKS_PER_PAGE
        page_items = blocks[start_index:start_index + _BLOCKS_PER_PAGE]

        if not blocks:
            text = _LIST_EMPTY_TEXT.get(lang, _LIST_EMPTY_TEXT["ru"])
        else:
            lines = []
            for block in page_items:
                if block.staff_id is None:
                    target = _CLINIC_WIDE_TARGET_LABEL.get(lang, _CLINIC_WIDE_TARGET_LABEL["ru"])
                else:
                    target = doctor_name_by_id.get(
                        block.staff_id, _UNKNOWN_DOCTOR_LABEL.get(lang, _UNKNOWN_DOCTOR_LABEL["ru"]),
                    )
                lines.append(
                    _BLOCK_LINE_TEXT.get(lang, _BLOCK_LINE_TEXT["ru"]).format(
                        id=block.id,
                        start=format_appointment_card_datetime(block.start_datetime),
                        end=format_appointment_card_datetime(block.end_datetime),
                        target=target,
                        reason=block.reason,
                    )
                )
            header = _LIST_HEADER_TEXT.get(lang, _LIST_HEADER_TEXT["ru"]).format(current=page, total=total_pages)
            text = header + "\n\n" + "\n\n".join(lines)

        await callback_query.answer('')
        await callback_query.message.edit_text(
            text, reply_markup=slot_blocking_list_kb(page_items, page, total_pages, lang=lang),
        )

    async def is_own_block(clinic_id: int, doctor_id: int | None, block_id: int) -> bool:
        """UI-only fast check to avoid showing a cancel-confirmation prompt for a
        block the current admin clearly cannot act on. This is NOT the authorization
        boundary -- SlotBlockingService.cancel_block re-validates clinic/doctor
        ownership server-side before actually cancelling.
        doctor_id is None for a clinic-scope admin (no ownership restriction).
        For an own-scope doctor, only their own blocks are theirs to act on."""
        if doctor_id is None:
            return True
        blocks = await slot_blocking_service.list_active_blocks(clinic_id)
        target = next((block for block in blocks if block.id == block_id), None)
        return target is not None and target.staff_id == doctor_id

    @router.callback_query(F.data == "slot_blocking_manage")
    async def open_manage(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        await state.clear()
        scope = await resolve_scope(callback_query, lang)
        if scope is None:
            return
        clinic_id, doctor_id = scope
        await render_blocks_list(callback_query, clinic_id, doctor_id, page=1, lang=lang)

    @router.callback_query(SlotBlockListCB.filter())
    async def paginate_blocks(
        callback_query: CallbackQuery, callback_data: SlotBlockListCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        scope = await resolve_scope(callback_query, lang)
        if scope is None:
            return
        clinic_id, doctor_id = scope
        await render_blocks_list(callback_query, clinic_id, doctor_id, callback_data.page, lang=lang)

    @router.callback_query(SlotBlockCancelCB.filter(F.step == "confirm"))
    async def cancel_block_prompt(
        callback_query: CallbackQuery, callback_data: SlotBlockCancelCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        scope = await resolve_scope(callback_query, lang)
        if scope is None:
            return
        clinic_id, doctor_id = scope
        if not await is_own_block(clinic_id, doctor_id, callback_data.block_id):
            await callback_query.answer(_BLOCK_UNAVAILABLE_TEXT.get(lang, _BLOCK_UNAVAILABLE_TEXT["ru"]), show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            _CANCEL_CONFIRM_PROMPT_TEXT.get(lang, _CANCEL_CONFIRM_PROMPT_TEXT["ru"]).format(id=callback_data.block_id),
            reply_markup=slot_blocking_cancel_confirm_kb(callback_data.block_id, lang=lang),
        )

    @router.callback_query(SlotBlockCancelCB.filter(F.step == "execute"))
    async def cancel_block_execute(
        callback_query: CallbackQuery, callback_data: SlotBlockCancelCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        scope = await resolve_scope(callback_query, lang)
        if scope is None:
            return
        clinic_id, doctor_id = scope

        try:
            await slot_blocking_service.cancel_block(callback_query.from_user.id, callback_data.block_id)
        except BotException as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
        else:
            await callback_query.answer(_CANCEL_SUCCESS_ANSWER_TEXT.get(lang, _CANCEL_SUCCESS_ANSWER_TEXT["ru"]))

        await render_blocks_list(callback_query, clinic_id, doctor_id, page=1, lang=lang)

    return router
