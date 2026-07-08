import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.appointment_exceptions import AppointmentNotFoundError
from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import InvalidPhoneError, InvalidFullNameError, UserNotFoundError
from bot.handlers.utils.admin_utils.appointment_helpers import format_appointments_list
from bot.handlers.utils.admin_utils.confirmations import show_confirmation
from bot.handlers.utils.admin_utils.input_helpers import (
    ask_full_name,
    edit_full_name,
    phone_processing,
    full_name_processing,
    edit_phone,
    ask_phone,
)
from bot.keyboards.admin.record_management_kb.appointment_search_kb import (
    appointment_search_kb,
    appointment_search_phone_kb,
    appointment_search_name_kb,
)
from bot.keyboards.utils.utils_kb import cancel_kb
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.states.admin.record_management.appointment_states import AppointmentSearchStates
from bot.utils.role import RoleFilter
from bot.validators.validators import SEARCH_NAME_PATTERN

logger = logging.getLogger(__name__)


def create_admin_appointment_search_router(appointment_repo, user_repo, staff_repo, clinic_repo):
    router = Router()

    appt_mng = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    @router.callback_query(F.data == "search_record")
    async def appointment_search(callback_query: CallbackQuery, state: FSMContext):
        await state.set_state(AppointmentSearchStates.appointment_search_variant)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            text='Выберите способ поиска:',
            reply_markup=appointment_search_kb()
        )

    @router.callback_query(F.data == "appointment_full_name_search")
    async def appointment_full_name_search(callback_query: CallbackQuery, state: FSMContext):
        await ask_full_name(
            callback_query, state,
            next_state=AppointmentSearchStates.appointment_search_name,
            reply_markup=cancel_kb(),
        )

    @router.message(AppointmentSearchStates.appointment_search_name, F.text)
    async def process_appointment_full_name_search(message: Message, state: FSMContext):
        if not await full_name_processing(
            message,
            state,
            next_state=AppointmentSearchStates.confirm_search,
            re_pattern=SEARCH_NAME_PATTERN
        ):
            return
        await show_confirmation(message, state, reply_markup=appointment_search_name_kb())

    @router.callback_query(F.data == "appointment_phone_search")
    async def appointment_phone_search(callback_query: CallbackQuery, state: FSMContext):
        await ask_phone(
            callback_query, state,
            AppointmentSearchStates.appointment_search_phone,
            reply_markup=cancel_kb(),
        )

    @router.message(AppointmentSearchStates.appointment_search_phone, F.text)
    async def process_appointment_phone_search(message: Message, state: FSMContext):
        if not await phone_processing(
            message,
            state,
            final_state=AppointmentSearchStates.confirm_search,
        ):
            return
        await show_confirmation(message, state, reply_markup=appointment_search_phone_kb())

    @router.callback_query(AppointmentSearchStates.confirm_search, F.data == "appointment_search_edit_full_name")
    async def appointment_search_edit_full_name(callback: CallbackQuery, state: FSMContext):
        await edit_full_name(callback, state, edit_state=AppointmentSearchStates.edit_full_name, reply_markup=cancel_kb())

    @router.message(AppointmentSearchStates.edit_full_name, F.text)
    async def process_edit_full_name(message: Message, state: FSMContext):
        if not await full_name_processing(
            message,
            state,
            next_state=AppointmentSearchStates.confirm_search,
            re_pattern=SEARCH_NAME_PATTERN
        ):
            return
        await show_confirmation(message, state, reply_markup=appointment_search_name_kb())

    @router.callback_query(
        AppointmentSearchStates.confirm_search,
        F.data == "appointment_search_edit_phone"
    )
    async def appointment_search_edit_phone(callback: CallbackQuery, state: FSMContext):
        await edit_phone(callback, state, edit_state=AppointmentSearchStates.edit_phone, reply_markup=cancel_kb())

    @router.message(AppointmentSearchStates.edit_phone, F.text)
    async def process_edit_phone(message: Message, state: FSMContext):
        if not await phone_processing(
            message,
            state,
            final_state=AppointmentSearchStates.confirm_search,
        ):
            return
        await show_confirmation(message, state, reply_markup=appointment_search_phone_kb())

    @router.callback_query(F.data == "get_all_appointments")
    async def get_all_appointments(callback_query: CallbackQuery, state: FSMContext):
        """Показать все записи"""
        try:
            appointments = await appt_mng.get_all_appointments()
        except BotException as e:
            await callback_query.answer(f"Ошибка: {e}", show_alert=True)
            return

        if not appointments:
            await callback_query.answer("Записей не найдено", show_alert=True)
            return

        text = format_appointments_list("Все записи (сначала новые)", appointments)
        await callback_query.message.edit_text(text, reply_markup=None)
        await callback_query.answer()

    @router.callback_query(F.data == "approve_appointment_search")
    async def approve_appointment_search(callback_query: CallbackQuery, state: FSMContext):
        """Завершить поиск и показать результаты"""
        data = await state.get_data()

        try:
            appointments = await appt_mng.search_appointments(data)
        except (InvalidPhoneError, InvalidFullNameError, UserNotFoundError, AppointmentNotFoundError) as e:
            await callback_query.answer(str(e), show_alert=True)
            await state.clear()
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка поиска: {e}", show_alert=True)
            await state.clear()
            return

        search_key = data.get("phone") or data.get("full_name", "")
        text = format_appointments_list(f"Записи по '{search_key}'", appointments)
        await callback_query.message.edit_text(text, reply_markup=None)
        await callback_query.answer()
        await state.clear()

    @router.callback_query(F.data == "noop")
    async def noop_button(callback_query: CallbackQuery):
        """Обработчик для неактивных кнопок"""
        await callback_query.answer()

    return router
