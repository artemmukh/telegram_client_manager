import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.exceptions import BotException, PaginationError
from bot.exceptions.user_exceptions import (
    PHONE_ALREADY_EXISTS_MESSAGE,
    InvalidFullNameError,
    InvalidPhoneError,
    PhoneAlreadyExistsError,
    SamePhoneError,
    UserNotFoundError,
    ValidationError,
)
from bot.handlers.utils.admin_utils import appointment_helpers as ah
from bot.handlers.utils.admin_utils.client_browser_helpers import (
    CLIENT_NOT_FOUND_TEXT,
    edit_tracked_message,
    remember_tracked_message,
    render_client_card,
)
from bot.handlers.utils.admin_utils.confirmations import build_client_text, show_confirmation
from bot.handlers.utils.admin_utils.input_helpers import (
    ask_full_name,
    ask_phone,
    edit_full_name,
    edit_phone,
    full_name_processing,
    phone_processing,
)
from bot.keyboards.admin.client_management_kb.client_browser_cb import (
    ClientActionCB,
    ClientCardCB,
    ClientPageCB,
)
from bot.keyboards.admin.client_management_kb.client_browser_kb import (
    client_browser_back_to_search_kb,
    client_browser_cancel_edit_kb,
    client_browser_confirm_name_kb,
    client_browser_confirm_phone_kb,
    client_browser_search_kb,
    client_confirm_new_name_kb,
    client_confirm_new_phone_kb,
    client_delete_confirm_kb,
    client_list_kb,
)
from bot.models.user import User
from bot.services.appointment.appointment_management import AppointmentManagement
from bot.services.client.client_management import ClientManagement
from bot.services.client.client_pagination_service import ClientPaginationService
from bot.states.admin.client_management.client_browser_states import ClientBrowserStates
from bot.utils.role import RoleFilter
from bot.validators.validators import SEARCH_NAME_PATTERN

logger = logging.getLogger(__name__)

_CHOOSE_SEARCH_METHOD = {
    "ru": "Выберите способ:",
    "uz": "Usulni tanlang:",
}

_SEARCH_ERROR = {
    "ru": "Ошибка поиска клиента: {error}",
    "uz": "Mijozni qidirishda xatolik: {error}",
}

_UPDATE_ERROR = {
    "ru": "Ошибка обновления клиента: {error}",
    "uz": "Mijozni yangilashda xatolik: {error}",
}

_DELETE_CONFIRM_IRREVERSIBLE = {
    "ru": "⚠️ Удалить {name} безвозвратно?",
    "uz": "⚠️ {name} butunlay o'chirilsinmi?",
}

_DELETE_INCLUDES_APPOINTMENTS = {
    "ru": "\n\nБудут также удалены все его записи на приём ({count}).",
    "uz": "\n\nUning barcha qabul yozuvlari ham o'chiriladi ({count}).",
}

_UNLINK_CONFIRM = {
    "ru": "⚠️ Отвязать {name} от этой клиники?",
    "uz": "⚠️ {name} ushbu klinikadan uzilsinmi?",
}

_UNLINK_KEEPS_DATA = {
    "ru": "\n\nПрофиль клиента и его записи на приём не будут удалены — он останется зарегистрирован в других клиниках.",
    "uz": "\n\nMijoz profili va uning qabul yozuvlari o'chirilmaydi — u boshqa klinikalarda ro'yxatdan o'tgan bo'lib qoladi.",
}

_CLIENT_DELETED = {
    "ru": "Клиент удалён.",
    "uz": "Mijoz o'chirildi.",
}

_CLIENT_UNLINKED = {
    "ru": "Клиент отвязан от клиники.",
    "uz": "Mijoz klinikadan uzildi.",
}

_NEW_FULL_NAME_TITLE = {
    "ru": "Новое ФИ:",
    "uz": "Yangi F.I.Sh.:",
}

_NEW_PHONE_TITLE = {
    "ru": "Новый телефон:",
    "uz": "Yangi telefon:",
}

_LIST_TITLE_ALL = {
    "ru": "📋 Список всех клиентов",
    "uz": "📋 Barcha mijozlar ro'yxati",
}

_LIST_TITLE_SEARCH = {
    "ru": "🔍 Результаты поиска",
    "uz": "🔍 Qidiruv natijalari",
}

_LIST_HEADER = {
    "ru": "{prefix}{title} ({current} из {total_pages}) | Всего: {total_count}",
    "uz": "{prefix}{title} ({current} / {total_pages}) | Jami: {total_count}",
}

_EDIT_MESSAGE_ERROR = {
    "ru": "Ошибка редактирования сообщения",
    "uz": "Xabarni tahrirlashda xatolik",
}

_UNEXPECTED_ERROR = {
    "ru": "Произошла непредвиденная ошибка",
    "uz": "Kutilmagan xatolik yuz berdi",
}

_SAME_PHONE_MESSAGE = {
    "ru": "Введён такой же номер телефона. Пожалуйста, введите другой:",
    "uz": "Xuddi shu telefon raqami kiritildi. Iltimos, boshqasini kiriting:",
}


def create_admin_client_browser_router(
    user_repo, staff_repo, clinic_repo, appointment_repo=None, client_clinic_repo=None, *, instance: str = "zb",
):
    router = Router()

    cl_mng = ClientManagement(
        user_repository=user_repo,
        staff_repository=staff_repo,
        clinic_repository=clinic_repo,
        appointment_repository=appointment_repo,
        client_clinic_repository=client_clinic_repo,
    )
    pagination_service = ClientPaginationService(user_repo)
    appt_mng = AppointmentManagement(appointment_repo, user_repo, staff_repo, clinic_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    # --- Entry ---

    @router.callback_query(F.data == "browse_clients")
    async def browse_clients(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        await state.clear()
        await state.set_state(ClientBrowserStates.search_variant)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            _CHOOSE_SEARCH_METHOD.get(lang, _CHOOSE_SEARCH_METHOD["ru"]),
            reply_markup=client_browser_search_kb(lang),
        )
        await remember_tracked_message(state, callback_query.message)

    # --- Search by full name ---

    @router.callback_query(F.data == "cl_search_name")
    async def search_by_name(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        await ask_full_name(
            callback_query, state,
            next_state=ClientBrowserStates.search_name,
            reply_markup=client_browser_back_to_search_kb(lang),
            lang=lang,
        )

    @router.message(ClientBrowserStates.search_name, F.text)
    async def process_search_name(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        if not await full_name_processing(
            message, state,
            next_state=ClientBrowserStates.confirm_search,
            re_pattern=SEARCH_NAME_PATTERN,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_browser_confirm_name_kb(lang), lang=lang)

    @router.callback_query(ClientBrowserStates.confirm_search, F.data == "cl_edit_search_name")
    async def edit_search_name(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        await edit_full_name(
            callback_query, state,
            edit_state=ClientBrowserStates.edit_search_full_name,
            reply_markup=client_browser_back_to_search_kb(lang),
            lang=lang,
        )

    @router.message(ClientBrowserStates.edit_search_full_name, F.text)
    async def process_edit_search_name(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        if not await full_name_processing(
            message, state,
            next_state=ClientBrowserStates.confirm_search,
            re_pattern=SEARCH_NAME_PATTERN,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_browser_confirm_name_kb(lang), lang=lang)

    # --- Search by phone ---

    @router.callback_query(F.data == "cl_search_phone")
    async def search_by_phone(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        await ask_phone(
            callback_query, state,
            ClientBrowserStates.search_phone,
            reply_markup=client_browser_back_to_search_kb(lang),
            lang=lang,
        )

    @router.message(ClientBrowserStates.search_phone, F.text)
    async def process_search_phone(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        if not await phone_processing(message, state, final_state=ClientBrowserStates.confirm_search):
            return
        await show_confirmation(message, state, reply_markup=client_browser_confirm_phone_kb(lang), lang=lang)

    @router.callback_query(ClientBrowserStates.confirm_search, F.data == "cl_edit_search_phone")
    async def edit_search_phone(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        await edit_phone(
            callback_query, state,
            edit_state=ClientBrowserStates.edit_search_phone,
            reply_markup=client_browser_back_to_search_kb(lang),
            lang=lang,
        )

    @router.message(ClientBrowserStates.edit_search_phone, F.text)
    async def process_edit_search_phone(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        if not await phone_processing(message, state, final_state=ClientBrowserStates.confirm_search):
            return
        await show_confirmation(message, state, reply_markup=client_browser_confirm_phone_kb(lang), lang=lang)

    # --- Show all clients (skips search entirely) ---

    @router.callback_query(F.data == "cl_search_all")
    async def search_all(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        await state.clear()
        try:
            clinic = await cl_mng.get_admin_clinic(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        await render_list(callback_query, state, mode="list", page=1, clinic_id=clinic.clinic_id, lang=current_user.language)

    # --- Resolve the search query and show results ---

    @router.callback_query(ClientBrowserStates.confirm_search, F.data == "cl_approve_search")
    async def approve_search(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        data = await state.get_data()

        try:
            clinic = await cl_mng.get_admin_clinic(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        try:
            found = await cl_mng.search_client(data, clinic.clinic_id)
        except (InvalidPhoneError, InvalidFullNameError, UserNotFoundError) as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(_SEARCH_ERROR.get(lang, _SEARCH_ERROR["ru"]).format(error=e), show_alert=True)
            return

        if data.get("phone"):
            # Поиск по телефону всегда даёт ровно одно совпадение - карточка
            # напрямую, минуя список (возвращаться в "direct"-режиме некуда).
            await state.clear()
            await render_card(
                callback_query, state, client_id=found[0].ID, mode="direct", page=1, clinic_id=clinic.clinic_id,
                lang=lang,
            )
            return

        await state.update_data(search_data=data)
        await render_list(callback_query, state, mode="search", page=1, clinic_id=clinic.clinic_id, lang=lang)

    # --- Pagination ---

    @router.callback_query(ClientPageCB.filter())
    async def paginate(callback_query: CallbackQuery, callback_data: ClientPageCB, state: FSMContext, current_user: User):
        try:
            clinic = await cl_mng.get_admin_clinic(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        await render_list(
            callback_query, state, mode=callback_data.mode, page=callback_data.page, clinic_id=clinic.clinic_id,
            lang=current_user.language,
        )

    # --- Open a client's card ---

    @router.callback_query(ClientCardCB.filter())
    async def open_card(callback_query: CallbackQuery, callback_data: ClientCardCB, state: FSMContext, current_user: User):
        await render_card(
            callback_query, state,
            client_id=callback_data.client_id, mode=callback_data.mode, page=callback_data.page,
            lang=current_user.language,
        )

    # --- Card actions ---
    @router.callback_query(ClientActionCB.filter(F.action == "new_appointment"))
    async def new_appointment(
        callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        try:
            clinic = await cl_mng.get_admin_clinic(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        client = await cl_mng.get_client_by_id(callback_data.client_id, clinic.clinic_id)
        if client is None:
            await callback_query.answer(CLIENT_NOT_FOUND_TEXT.get(lang, CLIENT_NOT_FOUND_TEXT["ru"]), show_alert=True)
            return

        data = await state.get_data()
        await ah.begin_appointment_creation(
            appt_mng, callback_query, state,
            instance=instance,
            full_name=client.full_name, phone=client.phone,
            origin_client_id=callback_data.client_id, origin_mode=callback_data.mode, origin_page=callback_data.page,
            origin_search_data=data.get("search_data"),
            lang=lang,
        )

    @router.callback_query(ClientActionCB.filter(F.action == "edit_name"))
    async def start_edit_name(
        callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        await state.update_data(
            client_id=callback_data.client_id, mode=callback_data.mode, page=callback_data.page,
        )
        await edit_full_name(
            callback_query, state,
            edit_state=ClientBrowserStates.new_full_name,
            reply_markup=client_browser_cancel_edit_kb(
                callback_data.client_id, callback_data.mode, callback_data.page, lang,
            ),
            lang=lang,
        )

    @router.callback_query(ClientActionCB.filter(F.action == "edit_phone"))
    async def start_edit_phone(
        callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        await state.update_data(
            client_id=callback_data.client_id, mode=callback_data.mode, page=callback_data.page,
        )
        await edit_phone(
            callback_query, state,
            edit_state=ClientBrowserStates.new_phone,
            reply_markup=client_browser_cancel_edit_kb(
                callback_data.client_id, callback_data.mode, callback_data.page, lang,
            ),
            lang=lang,
        )

    @router.callback_query(ClientActionCB.filter(F.action == "delete"))
    async def start_delete(
        callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        try:
            clinic = await cl_mng.get_admin_clinic(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        user = await cl_mng.get_client_by_id(callback_data.client_id, clinic.clinic_id)
        if user is None:
            await callback_query.answer(CLIENT_NOT_FOUND_TEXT.get(lang, CLIENT_NOT_FOUND_TEXT["ru"]), show_alert=True)
            return

        appointments_count = await cl_mng.count_client_appointments(user.ID, clinic.clinic_id)
        is_last_clinic = await cl_mng.is_last_linked_clinic(user.ID, clinic.clinic_id)

        if is_last_clinic:
            text = _DELETE_CONFIRM_IRREVERSIBLE.get(lang, _DELETE_CONFIRM_IRREVERSIBLE["ru"]).format(name=user.full_name)
            if appointments_count > 0:
                text += _DELETE_INCLUDES_APPOINTMENTS.get(lang, _DELETE_INCLUDES_APPOINTMENTS["ru"]).format(count=appointments_count)
        else:
            text = _UNLINK_CONFIRM.get(lang, _UNLINK_CONFIRM["ru"]).format(name=user.full_name)
            text += _UNLINK_KEEPS_DATA.get(lang, _UNLINK_KEEPS_DATA["ru"])

        await state.set_state(ClientBrowserStates.confirm_delete)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            text,
            reply_markup=client_delete_confirm_kb(
                callback_data.client_id, callback_data.mode, callback_data.page, is_last_clinic=is_last_clinic, lang=lang,
            ),
        )

    @router.callback_query(ClientActionCB.filter(F.action == "cancel_delete"))
    async def cancel_delete(
        callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext, current_user: User,
    ):
        await render_card(
            callback_query, state,
            client_id=callback_data.client_id, mode=callback_data.mode, page=callback_data.page,
            lang=current_user.language,
        )

    @router.callback_query(ClientActionCB.filter(F.action == "confirm_delete"))
    async def confirm_delete(
        callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        try:
            clinic = await cl_mng.get_admin_clinic(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        try:
            fully_deleted = await cl_mng.delete_client(callback_data.client_id, clinic.clinic_id)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        result_text = (
            _CLIENT_DELETED.get(lang, _CLIENT_DELETED["ru"]) if fully_deleted
            else _CLIENT_UNLINKED.get(lang, _CLIENT_UNLINKED["ru"])
        )

        if callback_data.mode == "direct":
            await state.clear()
            await callback_query.answer(result_text, show_alert=True)
            await callback_query.message.edit_text(
                result_text, reply_markup=client_browser_search_kb(lang),
            )
            return

        await render_list(
            callback_query, state,
            mode=callback_data.mode, page=callback_data.page, clinic_id=clinic.clinic_id,
            prefix=f"✅ {result_text}\n\n", lang=lang,
        )

    @router.callback_query(ClientActionCB.filter(F.action == "cancel_edit"))
    async def cancel_edit(
        callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext, current_user: User,
    ):
        await render_card(
            callback_query, state,
            client_id=callback_data.client_id, mode=callback_data.mode, page=callback_data.page,
            lang=current_user.language,
        )

    # --- Collect and confirm new full name ---

    @router.message(ClientBrowserStates.new_full_name, F.text)
    async def process_new_full_name(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        if not await full_name_processing(
            message, state,
            next_state=ClientBrowserStates.confirm_new_full_name,
            re_pattern=SEARCH_NAME_PATTERN,
        ):
            return

        data = await state.get_data()
        await message.delete()
        await edit_tracked_message(
            message.bot, state,
            text=build_client_text(_NEW_FULL_NAME_TITLE.get(lang, _NEW_FULL_NAME_TITLE["ru"]), {"full_name": data["full_name"]}, lang),
            reply_markup=client_confirm_new_name_kb(data["client_id"], data["mode"], data["page"], lang),
        )

    @router.callback_query(ClientActionCB.filter(F.action == "retry_new_name"))
    async def retry_new_name(
        callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        await edit_full_name(
            callback_query, state,
            edit_state=ClientBrowserStates.new_full_name,
            reply_markup=client_browser_cancel_edit_kb(
                callback_data.client_id, callback_data.mode, callback_data.page, lang,
            ),
            lang=lang,
        )

    @router.callback_query(ClientActionCB.filter(F.action == "approve_new_name"))
    async def approve_new_name(
        callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        data = await state.get_data()

        try:
            clinic = await cl_mng.get_admin_clinic(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        try:
            await cl_mng.update_client_name(callback_data.client_id, data["full_name"], clinic.clinic_id)
        except (InvalidFullNameError, UserNotFoundError) as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(_UPDATE_ERROR.get(lang, _UPDATE_ERROR["ru"]).format(error=e), show_alert=True)
            return

        await render_card(
            callback_query, state,
            client_id=callback_data.client_id, mode=callback_data.mode, page=callback_data.page,
            clinic_id=clinic.clinic_id, lang=lang,
        )

    # --- Collect and confirm new phone ---

    @router.message(ClientBrowserStates.new_phone, F.text)
    async def process_new_phone(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        data = await state.get_data()
        client_id = data["client_id"]

        try:
            clinic = await cl_mng.get_admin_clinic(message.from_user.id)
        except BotException as e:
            await message.answer(str(e))
            return

        async def validate_update_phone(phone: str):
            user = await cl_mng.get_client_by_id(client_id, clinic.clinic_id)
            if user is None:
                raise UserNotFoundError(CLIENT_NOT_FOUND_TEXT.get(lang, CLIENT_NOT_FOUND_TEXT["ru"]))
            if phone == user.phone:
                raise SamePhoneError(_SAME_PHONE_MESSAGE.get(lang, _SAME_PHONE_MESSAGE["ru"]))
            if await cl_mng.is_phone_taken(phone):
                raise PhoneAlreadyExistsError(PHONE_ALREADY_EXISTS_MESSAGE)

        if not await phone_processing(
            message, state,
            validator=validate_update_phone,
            final_state=ClientBrowserStates.confirm_new_phone,
        ):
            return

        data = await state.get_data()
        await message.delete()
        await edit_tracked_message(
            message.bot, state,
            text=build_client_text(_NEW_PHONE_TITLE.get(lang, _NEW_PHONE_TITLE["ru"]), {"phone": data["phone"]}, lang),
            reply_markup=client_confirm_new_phone_kb(data["client_id"], data["mode"], data["page"], lang),
        )

    @router.callback_query(ClientActionCB.filter(F.action == "retry_new_phone"))
    async def retry_new_phone(
        callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        await edit_phone(
            callback_query, state,
            edit_state=ClientBrowserStates.new_phone,
            reply_markup=client_browser_cancel_edit_kb(
                callback_data.client_id, callback_data.mode, callback_data.page, lang,
            ),
            lang=lang,
        )

    @router.callback_query(ClientActionCB.filter(F.action == "approve_new_phone"))
    async def approve_new_phone(
        callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext, current_user: User,
    ):
        lang = current_user.language
        data = await state.get_data()

        try:
            clinic = await cl_mng.get_admin_clinic(callback_query.from_user.id)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        try:
            await cl_mng.update_client_phone(callback_data.client_id, data["phone"], clinic.clinic_id)
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(_UPDATE_ERROR.get(lang, _UPDATE_ERROR["ru"]).format(error=e), show_alert=True)
            return

        await render_card(
            callback_query, state,
            client_id=callback_data.client_id, mode=callback_data.mode, page=callback_data.page,
            clinic_id=clinic.clinic_id, lang=lang,
        )

    @router.callback_query(F.data == "noop")
    async def noop_button(callback_query: CallbackQuery):
        await callback_query.answer()

    # --- Shared renderers ---

    async def render_list(
        callback_query: CallbackQuery, state: FSMContext, *, mode: str, page: int, clinic_id: int, prefix: str = "",
        lang: str = "ru",
    ) -> None:
        try:
            search_data = None
            if mode == "search":
                data = await state.get_data()
                search_data = data.get("search_data") or {"full_name": data.get("full_name", "")}

            result = await pagination_service.paginate_clients(mode, page, clinic_id, search_data)

            title = _LIST_TITLE_ALL.get(lang, _LIST_TITLE_ALL["ru"]) if mode == "list" \
                else _LIST_TITLE_SEARCH.get(lang, _LIST_TITLE_SEARCH["ru"])
            text = _LIST_HEADER.get(lang, _LIST_HEADER["ru"]).format(
                prefix=prefix, title=title, current=result.current_page, total_pages=result.total_pages,
                total_count=result.total_count,
            )

            await callback_query.message.edit_text(
                text,
                reply_markup=client_list_kb(result.items, mode, result.current_page, result.total_pages, lang),
            )
            await callback_query.answer()
            await remember_tracked_message(state, callback_query.message)

        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback_query.answer()
            else:
                logger.warning(f"TelegramBadRequest in render_list: {e}")
                await callback_query.answer(_EDIT_MESSAGE_ERROR.get(lang, _EDIT_MESSAGE_ERROR["ru"]), show_alert=False)
        except PaginationError as e:
            logger.warning(f"Pagination error in render_list: {e}")
            await callback_query.answer(str(e), show_alert=True)
        except Exception as e:
            logger.exception(f"Unexpected error in render_list: {e}")
            await callback_query.answer(_UNEXPECTED_ERROR.get(lang, _UNEXPECTED_ERROR["ru"]), show_alert=True)

    async def render_card(
        callback_query: CallbackQuery, state: FSMContext, *,
        client_id: int, mode: str, page: int, clinic_id: int | None = None, lang: str = "ru",
    ) -> None:
        if clinic_id is None:
            try:
                clinic = await cl_mng.get_admin_clinic(callback_query.from_user.id)
            except BotException as e:
                await callback_query.answer(str(e), show_alert=True)
                return
            clinic_id = clinic.clinic_id
        await render_client_card(cl_mng, callback_query, state, client_id, mode, page, clinic_id, lang)

    return router
