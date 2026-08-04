
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.exceptions.exceptions import BotException
from bot.exceptions.user_exceptions import (
    PHONE_ALREADY_EXISTS_MESSAGE,
    InvalidPhoneError,
    InvalidFullNameError,
    PhoneAlreadyExistsError,
    ValidationError,
)
from bot.handlers.utils.admin_utils.confirmations import CONFIRM_TITLE, build_client_text, show_success, show_confirmation
from bot.handlers.utils.admin_utils.input_helpers import (
    ASK_PHONE_PROMPT,
    edit_full_name,
    edit_phone, ask_full_name, full_name_processing, phone_processing
)
from bot.keyboards.admin.client_management_kb.client_creation_kb import (
    client_creation_back_kb,
    client_creation_duplicate_name_kb,
    client_creation_kb,
)
from bot.models.user import User
from bot.services.client.client_management import ClientManagement
from bot.states.admin.client_management.client_creation_states import ClientCreationStates
from bot.utils.role import RoleFilter
from bot.validators.validators import SEARCH_NAME_PATTERN
from bot.validators.validators import validate_fields_filled

_PHONE_ALREADY_EXISTS = {
    "ru": "Пациент с таким номером телефона уже существует.",
    "uz": "Bunday telefon raqamiga ega bemor allaqachon mavjud.",
}

_CLIENT_CREATION_ERROR = {
    "ru": "Ошибка создания клиента: {error}",
    "uz": "Mijoz yaratishda xatolik: {error}",
}

_CLIENT_ADDED = {
    "ru": "Клиент успешно добавлен!",
    "uz": "Mijoz muvaffaqiyatli qo'shildi!",
}

_DUPLICATE_NAME_SINGLE = {
    "ru": "Клиент с именем {name} уже существует (телефон: {phone}). Продолжить создание?",
    "uz": "{name} ismli mijoz allaqachon mavjud (telefon: {phone}). Yaratishni davom ettirasizmi?",
}

_DUPLICATE_NAME_MULTIPLE = {
    "ru": "Клиенты с именем {name} уже существуют ({count} чел., например телефон: {phone}). Продолжить создание?",
    "uz": "{name} ismli mijozlar allaqachon mavjud ({count} kishi, masalan telefon: {phone}). Yaratishni davom ettirasizmi?",
}


def create_admin_client_creation_router(user_repo, staff_repo, clinic_repo, client_clinic_repo=None):

    router = Router()

    cl_mng = ClientManagement(user_repo, staff_repo, clinic_repo, client_clinic_repository=client_clinic_repo)

    async def validate_phone_available(phone: str):
        if await cl_mng.is_phone_taken(phone):
            raise PhoneAlreadyExistsError(PHONE_ALREADY_EXISTS_MESSAGE)


    router.message.filter(RoleFilter("admin"))
    router.callback_query.filter(RoleFilter("admin"))


    async def _begin_client_creation(event: CallbackQuery | Message, state: FSMContext, lang: str) -> None:
        try:
            clinic = await cl_mng.get_admin_clinic(event.from_user.id)
        except BotException as e:
            if isinstance(event, CallbackQuery):
                await event.answer(e.localized(lang), show_alert=True)
            else:
                await event.answer(e.localized(lang))
            return

        await state.update_data(clinic_id=clinic.clinic_id, clinic_name=clinic.name)
        await ask_full_name(
            event, state,
            next_state=ClientCreationStates.client_full_name,
            reply_markup=client_creation_back_kb(lang),
            lang=lang,
        )

    @router.callback_query(F.data == "create_client")
    async def create_client_name(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        await _begin_client_creation(callback_query, state, current_user.language)

    @router.message(F.text == "/create_client")
    async def create_client_name_message(message: Message, state: FSMContext, current_user: User):
        await _begin_client_creation(message, state, current_user.language)

    @router.message(ClientCreationStates.client_full_name, F.text)
    async def create_client_phone(message: Message, state: FSMContext, current_user: User):
       lang = current_user.language
       if not await full_name_processing(
           message, state, next_state=ClientCreationStates.client_phone, re_pattern=SEARCH_NAME_PATTERN, lang=lang,
       ):
           return
       await message.answer(text=ASK_PHONE_PROMPT.get(lang, ASK_PHONE_PROMPT["ru"]), reply_markup=client_creation_back_kb(lang))

    @router.message(ClientCreationStates.client_phone, F.text)
    async def confirm(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        if not await phone_processing(
                message,
                state,
                validator=validate_phone_available,
                final_state=ClientCreationStates.confirm_create,
                lang=lang,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_creation_kb(lang), lang=lang)

    @router.callback_query(
        ClientCreationStates.confirm_create,
        F.data == "client_creation_edit_full_name"
    )
    async def full_name_edition(callback: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        await edit_full_name(
            callback, state,
            edit_state=ClientCreationStates.edit_full_name,
            reply_markup=client_creation_back_kb(lang),
            lang=lang,
        )

    @router.message(ClientCreationStates.edit_full_name, F.text)
    async def process_full_name_edition(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        if not await full_name_processing(
            message, state,
            next_state=ClientCreationStates.confirm_create, re_pattern=SEARCH_NAME_PATTERN, lang=lang,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_creation_kb(lang), lang=lang)

    @router.callback_query(
        ClientCreationStates.confirm_create,
        F.data == "client_creation_edit_phone"
    )
    async def phone_edition(callback: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        await edit_phone(
            callback, state,
            edit_state=ClientCreationStates.edit_phone,
            reply_markup=client_creation_back_kb(lang),
            lang=lang,
        )

    @router.message(ClientCreationStates.edit_phone, F.text)
    async def process_phone_edition(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        if not await phone_processing(message,
                state,
                validator=validate_phone_available,
                final_state=ClientCreationStates.confirm_create,
                lang=lang,
        ):
            return
        await show_confirmation(message, state, reply_markup=client_creation_kb(lang), lang=lang)


    async def _finalize_client_creation(callback_query: CallbackQuery, state: FSMContext, data: dict, lang: str) -> None:
        try:
            user = await cl_mng.create_client(callback_query.from_user.id, data)
        except PhoneAlreadyExistsError:
            await state.clear()
            await callback_query.message.edit_text(
                _PHONE_ALREADY_EXISTS.get(lang, _PHONE_ALREADY_EXISTS["ru"]),
                reply_markup=None,
            )
            await callback_query.answer('')
            return
        except (InvalidPhoneError, InvalidFullNameError) as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
            return
        except BotException as e:
            await callback_query.answer(_CLIENT_CREATION_ERROR.get(lang, _CLIENT_CREATION_ERROR["ru"]).format(error=e.localized(lang)), show_alert=True)
            return

        await show_success(
            callback_query,
            _CLIENT_ADDED.get(lang, _CLIENT_ADDED["ru"]),
            lang,
            full_name=user.full_name,
            phone=user.phone,
            clinic_name=user.clinic_name,
        )

        await state.clear()

    @router.callback_query(F.data == "client_creation_finish")
    async def client_creation_finish(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        data = await state.get_data()

        try:
            validate_fields_filled(data)
        except ValidationError as e:
            await callback_query.answer(e.localized(lang), show_alert=True)
            return

        duplicates = await cl_mng.find_clients_by_exact_name(data['full_name'], data['clinic_id'])
        if duplicates:
            if len(duplicates) == 1:
                text = _DUPLICATE_NAME_SINGLE.get(lang, _DUPLICATE_NAME_SINGLE["ru"]).format(
                    name=data['full_name'], phone=duplicates[0].phone,
                )
            else:
                text = _DUPLICATE_NAME_MULTIPLE.get(lang, _DUPLICATE_NAME_MULTIPLE["ru"]).format(
                    name=data['full_name'], count=len(duplicates), phone=duplicates[0].phone,
                )
            await state.set_state(ClientCreationStates.confirm_duplicate_name)
            await callback_query.message.edit_text(text, reply_markup=client_creation_duplicate_name_kb(lang))
            await callback_query.answer('')
            return

        await _finalize_client_creation(callback_query, state, data, lang)

    @router.callback_query(ClientCreationStates.confirm_duplicate_name, F.data == "client_creation_duplicate_confirm")
    async def client_creation_duplicate_confirm(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        data = await state.get_data()
        await _finalize_client_creation(callback_query, state, data, current_user.language)

    @router.callback_query(ClientCreationStates.confirm_duplicate_name, F.data == "client_creation_duplicate_cancel")
    async def client_creation_duplicate_cancel(callback_query: CallbackQuery, state: FSMContext, current_user: User):
        lang = current_user.language
        await state.set_state(ClientCreationStates.confirm_create)
        data = await state.get_data()
        await callback_query.answer('')
        await callback_query.message.edit_text(
            build_client_text(CONFIRM_TITLE.get(lang, CONFIRM_TITLE["ru"]), data, lang),
            reply_markup=client_creation_kb(lang),
        )


    return router
