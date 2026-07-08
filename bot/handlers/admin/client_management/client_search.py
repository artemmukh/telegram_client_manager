import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import InvalidPhoneError, InvalidFullNameError, UserNotFoundError
from bot.handlers.utils.admin_utils.confirmations import show_confirmation
from bot.handlers.utils.admin_utils.input_helpers import ask_full_name, edit_full_name, phone_processing, \
    full_name_processing, edit_phone, ask_phone
from bot.keyboards.admin.client_management_kb.client_search_kb import client_search_kb, \
    client_search_phone_kb, client_search_name_kb
from bot.keyboards.admin.client_management_kb.client_pagination_kb import pagination_keyboard
from bot.utils.role import RoleFilter
from bot.utils.pagination import parse_pagination_callback
from bot.validators.validators import SEARCH_NAME_PATTERN
from bot.services.client.client_management import ClientManagement
from bot.services.client.client_pagination_service import ClientPaginationService
from bot.states.admin.client_management.client_search_states import ClientSearchStates

logger = logging.getLogger(__name__)


def create_admin_client_search_router(user_repo, staff_repo, clinic_repo):
    router = Router()

    cl_mng = ClientManagement(user_repo, staff_repo, clinic_repo)

    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))

    @router.callback_query(F.data == "search_client")
    async def client_search(callback_query: CallbackQuery):
        await callback_query.answer('')
        await callback_query.message.edit_text(text='Выберите метод поиска:', reply_markup=client_search_kb())

    @router.callback_query(F.data == "client_full_name_search")
    async def client_full_name_search(callback_query: CallbackQuery, state: FSMContext):
        await ask_full_name(callback_query, state, next_state=ClientSearchStates.client_search_name)

    @router.message(ClientSearchStates.client_search_name, F.text)
    async def process_client_full_name_search(message: Message, state: FSMContext):
        if not await full_name_processing(message, state, next_state=ClientSearchStates.confirm_search, re_pattern=SEARCH_NAME_PATTERN):
            return
        await show_confirmation(message, state, reply_markup=client_search_name_kb())

    @router.callback_query(F.data == "client_phone_search")
    async def client_phone_search(callback_query: CallbackQuery, state: FSMContext):
        await ask_phone(callback_query, state, ClientSearchStates.client_search_phone)

    @router.message(ClientSearchStates.client_search_phone, F.text)
    async def process_client_phone_search(message: Message, state: FSMContext):
        if not await phone_processing(
            message,
            state,
            final_state=ClientSearchStates.confirm_search,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_search_phone_kb())

    @router.callback_query(ClientSearchStates.confirm_search, F.data == "client_search_edit_full_name")
    async def full_name_edition(callback: CallbackQuery, state: FSMContext):
        await edit_full_name(callback, state, edit_state=ClientSearchStates.edit_full_name)

    @router.message(ClientSearchStates.edit_full_name, F.text)
    async def process_full_name_edition(message: Message, state: FSMContext):
        if not await full_name_processing(
                message, state,
                next_state=ClientSearchStates.confirm_search, re_pattern=SEARCH_NAME_PATTERN
        ):
            return
        await show_confirmation(message, state, reply_markup=client_search_name_kb())

    @router.callback_query(
        ClientSearchStates.confirm_search,
        F.data == "client_search_edit_phone"
    )
    async def phone_edition(callback: CallbackQuery, state: FSMContext):
        await edit_phone(callback, state, edit_state=ClientSearchStates.edit_phone)

    @router.message(ClientSearchStates.edit_phone, F.text)
    async def process_phone_edition(message: Message, state: FSMContext):
        if not await phone_processing(
            message,
            state,
            final_state=ClientSearchStates.confirm_search,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_search_phone_kb())

    @router.callback_query(F.data == "get_all_clients")
    async def get_all_clients(callback_query: CallbackQuery, state: FSMContext):
        """Показать всех клиентов с пагинацией"""
        pagination_service = ClientPaginationService(user_repo)
        result = await pagination_service.paginate_clients("list", 1)

        text = pagination_service.format_clients_text(
            result.items,
            result.current_page,
            result.total_pages,
            "list"
        )
        keyboard = pagination_keyboard("list", result.current_page, result.total_pages)

        await callback_query.message.edit_text(text, reply_markup=keyboard)
        await callback_query.answer()

    @router.callback_query(F.data == "approve_client_search")
    async def client_search_finish(callback_query: CallbackQuery, state: FSMContext):
        """Завершить поиск и показать результаты с пагинацией"""
        data = await state.get_data()

        try:
            found = await cl_mng.search_client(data)
        except (InvalidPhoneError, InvalidFullNameError, UserNotFoundError) as e:
            await callback_query.answer(str(e), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(f"Ошибка поиска клиента: {e}", show_alert=True)
            return

        # Сохраняем search_data в state для пагинации
        await state.update_data(search_data=data)

        # Показываем первую страницу результатов поиска с пагинацией
        pagination_service = ClientPaginationService(user_repo)
        result = await pagination_service.paginate_clients("search", 1, data)

        text = pagination_service.format_clients_text(
            result.items,
            result.current_page,
            result.total_pages,
            "search"
        )
        keyboard = pagination_keyboard("search", result.current_page, result.total_pages)

        await callback_query.message.edit_text(text, reply_markup=keyboard)
        await callback_query.answer()

    @router.callback_query(F.data.startswith("page:"))
    async def paginate_clients(callback_query: CallbackQuery, state: FSMContext):
        """Обработчик пагинации для поиска и полного листинга"""
        try:
            mode, page_num = parse_pagination_callback(callback_query.data)

            # Для search режима извлекаем search_data из state
            search_data = None
            if mode == "search":
                data = await state.get_data()
                search_data = data.get("search_data") or {"full_name": data.get("full_name", "")}

            # Получаем пагинированные результаты
            pagination_service = ClientPaginationService(user_repo)
            result = await pagination_service.paginate_clients(mode, page_num, search_data)

            # Форматируем текст и показываем
            text = pagination_service.format_clients_text(
                result.items,
                result.current_page,
                result.total_pages,
                mode
            )
            keyboard = pagination_keyboard(mode, result.current_page, result.total_pages)

            await callback_query.message.edit_text(text, reply_markup=keyboard)
            await callback_query.answer()

        except TelegramBadRequest as e:
            # "message is not modified" — обычная ситуация, просто закрыть спиннер
            if "message is not modified" in str(e):
                await callback_query.answer()
            else:
                logger.warning(f"TelegramBadRequest in paginate_clients: {e}")
                await callback_query.answer("Ошибка редактирования сообщения", show_alert=False)
        except Exception as e:
            logger.exception(f"Error in paginate_clients: {e}")
            await callback_query.answer(f"Ошибка: {str(e)}", show_alert=True)

    @router.callback_query(F.data == "noop")
    async def noop_button(callback_query: CallbackQuery):
        """Обработчик для неактивных кнопок (например, показатель страницы)"""
        await callback_query.answer()

    return router
