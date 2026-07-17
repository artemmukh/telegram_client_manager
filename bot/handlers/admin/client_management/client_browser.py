import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.exceptions.exceptions import BotException, PaginationError
from bot.exceptions.user_exceptions import (
    InvalidFullNameError,
    InvalidPhoneError,
    PhoneAlreadyExistsError,
    SamePhoneError,
    UserNotFoundError,
    ValidationError,
)
from bot.handlers.utils.admin_utils.client_browser_helpers import (
    build_client_card_text,
    edit_tracked_message,
    remember_tracked_message,
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
    client_card_kb,
    client_confirm_new_name_kb,
    client_confirm_new_phone_kb,
    client_delete_confirm_kb,
    client_list_kb,
)
from bot.services.client.client_management import ClientManagement
from bot.services.client.client_pagination_service import ClientPaginationService
from bot.states.admin.client_management.client_browser_states import ClientBrowserStates
from bot.utils.role import RoleFilter
from bot.validators.validators import FULL_NAME_PATTERN, SEARCH_NAME_PATTERN

logger = logging.getLogger(__name__)


def create_admin_client_browser_router(user_repo, staff_repo, clinic_repo):
    router = Router()

    cl_mng = ClientManagement(user_repo, staff_repo, clinic_repo)
    pagination_service = ClientPaginationService(user_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    # --- Entry ---

    @router.callback_query(F.data == "browse_clients")
    async def browse_clients(callback_query: CallbackQuery, state: FSMContext):
        await state.clear()
        await state.set_state(ClientBrowserStates.search_variant)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            "Выберите способ:",
            reply_markup=client_browser_search_kb(),
        )
        await remember_tracked_message(state, callback_query.message)

    # --- Search by full name ---

    @router.callback_query(F.data == "cl_search_name")
    async def search_by_name(callback_query: CallbackQuery, state: FSMContext):
        await ask_full_name(
            callback_query, state,
            next_state=ClientBrowserStates.search_name,
            reply_markup=client_browser_back_to_search_kb(),
        )

    @router.message(ClientBrowserStates.search_name, F.text)
    async def process_search_name(message: Message, state: FSMContext):
        if not await full_name_processing(
            message, state,
            next_state=ClientBrowserStates.confirm_search,
            re_pattern=SEARCH_NAME_PATTERN,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_browser_confirm_name_kb())

    @router.callback_query(ClientBrowserStates.confirm_search, F.data == "cl_edit_search_name")
    async def edit_search_name(callback_query: CallbackQuery, state: FSMContext):
        await edit_full_name(
            callback_query, state,
            edit_state=ClientBrowserStates.edit_search_full_name,
            reply_markup=client_browser_back_to_search_kb(),
        )

    @router.message(ClientBrowserStates.edit_search_full_name, F.text)
    async def process_edit_search_name(message: Message, state: FSMContext):
        if not await full_name_processing(
            message, state,
            next_state=ClientBrowserStates.confirm_search,
            re_pattern=SEARCH_NAME_PATTERN,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_browser_confirm_name_kb())

    # --- Search by phone ---

    @router.callback_query(F.data == "cl_search_phone")
    async def search_by_phone(callback_query: CallbackQuery, state: FSMContext):
        await ask_phone(
            callback_query, state,
            ClientBrowserStates.search_phone,
            reply_markup=client_browser_back_to_search_kb(),
        )

    @router.message(ClientBrowserStates.search_phone, F.text)
    async def process_search_phone(message: Message, state: FSMContext):
        if not await phone_processing(message, state, final_state=ClientBrowserStates.confirm_search):
            return
        await show_confirmation(message, state, reply_markup=client_browser_confirm_phone_kb())

    @router.callback_query(ClientBrowserStates.confirm_search, F.data == "cl_edit_search_phone")
    async def edit_search_phone(callback_query: CallbackQuery, state: FSMContext):
        await edit_phone(
            callback_query, state,
            edit_state=ClientBrowserStates.edit_search_phone,
            reply_markup=client_browser_back_to_search_kb(),
        )

    @router.message(ClientBrowserStates.edit_search_phone, F.text)
    async def process_edit_search_phone(message: Message, state: FSMContext):
        if not await phone_processing(message, state, final_state=ClientBrowserStates.confirm_search):
            return
        await show_confirmation(message, state, reply_markup=client_browser_confirm_phone_kb())

    # --- Show all clients (skips search entirely) ---

    @router.callback_query(F.data == "cl_search_all")
    async def search_all(callback_query: CallbackQuery, state: FSMContext):
        await state.clear()
        await render_list(callback_query, state, mode="list", page=1)

    # --- Resolve the search query and show results ---

    @router.callback_query(ClientBrowserStates.confirm_search, F.data == "cl_approve_search")
    async def approve_search(callback_query: CallbackQuery, state: FSMContext):
        data = await state.get_data()

        try:
            found = await cl_mng.search_client(data)
        except (InvalidPhoneError, InvalidFullNameError, UserNotFoundError) as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка поиска клиента: {e}", show_alert=True)
            return

        if data.get("phone"):
            # Поиск по телефону всегда даёт ровно одно совпадение - карточка
            # напрямую, минуя список (возвращаться в "direct"-режиме некуда).
            await state.clear()
            await render_card(callback_query, state, client_id=found[0].ID, mode="direct", page=1)
            return

        await state.update_data(search_data=data)
        await render_list(callback_query, state, mode="search", page=1)

    # --- Pagination ---

    @router.callback_query(ClientPageCB.filter())
    async def paginate(callback_query: CallbackQuery, callback_data: ClientPageCB, state: FSMContext):
        await render_list(callback_query, state, mode=callback_data.mode, page=callback_data.page)

    # --- Open a client's card ---

    @router.callback_query(ClientCardCB.filter())
    async def open_card(callback_query: CallbackQuery, callback_data: ClientCardCB, state: FSMContext):
        await render_card(
            callback_query, state,
            client_id=callback_data.client_id, mode=callback_data.mode, page=callback_data.page,
        )

    # --- Card actions ---

    @router.callback_query(ClientActionCB.filter(F.action == "edit_name"))
    async def start_edit_name(callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext):
        await state.update_data(
            client_id=callback_data.client_id, mode=callback_data.mode, page=callback_data.page,
        )
        await edit_full_name(
            callback_query, state,
            edit_state=ClientBrowserStates.new_full_name,
            reply_markup=client_browser_cancel_edit_kb(
                callback_data.client_id, callback_data.mode, callback_data.page,
            ),
        )

    @router.callback_query(ClientActionCB.filter(F.action == "edit_phone"))
    async def start_edit_phone(callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext):
        await state.update_data(
            client_id=callback_data.client_id, mode=callback_data.mode, page=callback_data.page,
        )
        await edit_phone(
            callback_query, state,
            edit_state=ClientBrowserStates.new_phone,
            reply_markup=client_browser_cancel_edit_kb(
                callback_data.client_id, callback_data.mode, callback_data.page,
            ),
        )

    @router.callback_query(ClientActionCB.filter(F.action == "delete"))
    async def start_delete(callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext):
        user = await cl_mng.get_client_by_id(callback_data.client_id)
        if user is None:
            await callback_query.answer("Клиент не найден.", show_alert=True)
            return

        await state.set_state(ClientBrowserStates.confirm_delete)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            f"⚠️ Удалить {user.full_name} безвозвратно?",
            reply_markup=client_delete_confirm_kb(
                callback_data.client_id, callback_data.mode, callback_data.page,
            ),
        )

    @router.callback_query(ClientActionCB.filter(F.action == "cancel_delete"))
    async def cancel_delete(callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext):
        await render_card(
            callback_query, state,
            client_id=callback_data.client_id, mode=callback_data.mode, page=callback_data.page,
        )

    @router.callback_query(ClientActionCB.filter(F.action == "confirm_delete"))
    async def confirm_delete(callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext):
        try:
            await cl_mng.delete_client(callback_data.client_id)
        except BotException as e:
            await callback_query.answer(str(e), show_alert=True)
            return

        if callback_data.mode == "direct":
            await state.clear()
            await callback_query.answer("Клиент удалён.", show_alert=True)
            await callback_query.message.edit_text(
                "Клиент удалён.", reply_markup=client_browser_search_kb(),
            )
            return

        await render_list(
            callback_query, state,
            mode=callback_data.mode, page=callback_data.page, prefix="✅ Клиент удалён.\n\n",
        )

    @router.callback_query(ClientActionCB.filter(F.action == "cancel_edit"))
    async def cancel_edit(callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext):
        await render_card(
            callback_query, state,
            client_id=callback_data.client_id, mode=callback_data.mode, page=callback_data.page,
        )

    # --- Collect and confirm new full name ---

    @router.message(ClientBrowserStates.new_full_name, F.text)
    async def process_new_full_name(message: Message, state: FSMContext):
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
            text=build_client_text("Новое ФИ:", {"full_name": data["full_name"]}),
            reply_markup=client_confirm_new_name_kb(data["client_id"], data["mode"], data["page"]),
        )

    @router.callback_query(ClientActionCB.filter(F.action == "retry_new_name"))
    async def retry_new_name(callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext):
        await edit_full_name(
            callback_query, state,
            edit_state=ClientBrowserStates.new_full_name,
            reply_markup=client_browser_cancel_edit_kb(
                callback_data.client_id, callback_data.mode, callback_data.page,
            ),
        )

    @router.callback_query(ClientActionCB.filter(F.action == "approve_new_name"))
    async def approve_new_name(callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext):
        data = await state.get_data()

        try:
            await cl_mng.update_client_name(callback_data.client_id, data["full_name"])
        except (InvalidFullNameError, UserNotFoundError) as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка обновления клиента: {e}", show_alert=True)
            return

        await render_card(
            callback_query, state,
            client_id=callback_data.client_id, mode=callback_data.mode, page=callback_data.page,
        )

    # --- Collect and confirm new phone ---

    @router.message(ClientBrowserStates.new_phone, F.text)
    async def process_new_phone(message: Message, state: FSMContext):
        data = await state.get_data()
        client_id = data["client_id"]

        async def validate_update_phone(phone: str):
            user = await cl_mng.get_client_by_id(client_id)
            if user is None:
                raise UserNotFoundError("Клиент не найден.")
            if phone == user.phone:
                raise SamePhoneError("Введён такой же номер телефона. Пожалуйста, введите другой:")
            if await cl_mng.is_phone_taken(phone):
                raise PhoneAlreadyExistsError("Номер уже зарегистрирован. Пожалуйста, введите другой:")

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
            text=build_client_text("Новый телефон:", {"phone": data["phone"]}),
            reply_markup=client_confirm_new_phone_kb(data["client_id"], data["mode"], data["page"]),
        )

    @router.callback_query(ClientActionCB.filter(F.action == "retry_new_phone"))
    async def retry_new_phone(callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext):
        await edit_phone(
            callback_query, state,
            edit_state=ClientBrowserStates.new_phone,
            reply_markup=client_browser_cancel_edit_kb(
                callback_data.client_id, callback_data.mode, callback_data.page,
            ),
        )

    @router.callback_query(ClientActionCB.filter(F.action == "approve_new_phone"))
    async def approve_new_phone(callback_query: CallbackQuery, callback_data: ClientActionCB, state: FSMContext):
        data = await state.get_data()

        try:
            await cl_mng.update_client_phone(callback_data.client_id, data["phone"])
        except ValidationError as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка обновления клиента: {e}", show_alert=True)
            return

        await render_card(
            callback_query, state,
            client_id=callback_data.client_id, mode=callback_data.mode, page=callback_data.page,
        )

    @router.callback_query(F.data == "noop")
    async def noop_button(callback_query: CallbackQuery):
        await callback_query.answer()

    # --- Shared renderers ---

    async def render_list(
        callback_query: CallbackQuery, state: FSMContext, *, mode: str, page: int, prefix: str = "",
    ) -> None:
        try:
            search_data = None
            if mode == "search":
                data = await state.get_data()
                search_data = data.get("search_data") or {"full_name": data.get("full_name", "")}

            result = await pagination_service.paginate_clients(mode, page, search_data)

            title = "📋 Список всех клиентов" if mode == "list" else "🔍 Результаты поиска"
            text = f"{prefix}{title} ({result.current_page} из {result.total_pages}) | Всего: {result.total_count}"

            await callback_query.message.edit_text(
                text,
                reply_markup=client_list_kb(result.items, mode, result.current_page, result.total_pages),
            )
            await callback_query.answer()
            await remember_tracked_message(state, callback_query.message)

        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback_query.answer()
            else:
                logger.warning(f"TelegramBadRequest in render_list: {e}")
                await callback_query.answer("Ошибка редактирования сообщения", show_alert=False)
        except PaginationError as e:
            logger.warning(f"Pagination error in render_list: {e}")
            await callback_query.answer(str(e), show_alert=True)
        except Exception as e:
            logger.exception(f"Unexpected error in render_list: {e}")
            await callback_query.answer("Произошла непредвиденная ошибка", show_alert=True)

    async def render_card(
        callback_query: CallbackQuery, state: FSMContext, *, client_id: int, mode: str, page: int,
    ) -> None:
        user = await cl_mng.get_client_by_id(client_id)
        if user is None:
            await callback_query.answer("Клиент не найден.", show_alert=True)
            return

        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_client_card_text(user),
            reply_markup=client_card_kb(client_id, mode, page),
        )
        await remember_tracked_message(state, callback_query.message)

    return router
