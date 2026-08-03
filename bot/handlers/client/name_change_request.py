from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.exceptions.exceptions import BotException
from bot.handlers.utils.admin_utils.input_helpers import full_name_processing
from bot.models.user import User
from bot.services.client.client_management import ClientManagement
from bot.services.client.client_notifications import ClientNotificationService
from bot.states.name_change_states import NameChangeStates
from bot.utils.role import RoleFilter
from bot.validators.validators import FULL_NAME_PATTERN

_BACK_BUTTON_TEXT = {
    "ru": "⬅️ Назад",
    "uz": "⬅️ Orqaga",
}

_ENTER_NEW_NAME_PROMPT = {
    "ru": (
        "👤 Введите ваше новое ФИ.\n\n"
        "Пожалуйста, используйте реальные данные.\n"
        "Они будут отображаться врачу во время записи на приём."
    ),
    "uz": (
        "👤 Yangi F.I.Sh.ingizni kiriting.\n\n"
        "Iltimos, haqiqiy ma'lumotlardan foydalaning.\n"
        "Ular qabulga yozilishda shifokorga ko'rsatiladi."
    ),
}

_REQUEST_SENT = {
    "ru": "✅ Запрос на смену ФИ отправлен администратору клиники. Ожидайте решения.",
    "uz": "✅ F.I.Sh.ni o'zgartirish so'rovi klinika administratoriga yuborildi. Qarorni kuting.",
}


def _back_to_profile_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text=_BACK_BUTTON_TEXT.get(lang, _BACK_BUTTON_TEXT["ru"]), callback_data="profile_personal_data",
            )
        ]]
    )


def create_name_change_request_router(
        client_management_service: ClientManagement,
        client_notification_service: ClientNotificationService,
) -> Router:
    router = Router()

    router.message.filter(RoleFilter("*"))
    router.callback_query.filter(RoleFilter("*"))

    @router.callback_query(F.data == "profile_change_name")
    async def start_name_change(callback_query: CallbackQuery, state: FSMContext, current_user: User | None = None):
        lang = current_user.language if current_user else "ru"
        await state.set_state(NameChangeStates.entering_name)
        await callback_query.answer('')
        await callback_query.message.edit_text(
            _ENTER_NEW_NAME_PROMPT.get(lang, _ENTER_NEW_NAME_PROMPT["ru"]),
            reply_markup=_back_to_profile_kb(lang),
        )

    @router.message(NameChangeStates.entering_name, F.text)
    async def process_name_change(message: Message, state: FSMContext, current_user: User):
        lang = current_user.language
        if not await full_name_processing(
                message, state, next_state=NameChangeStates.entering_name, re_pattern=FULL_NAME_PATTERN, lang=lang):
            return

        data = await state.get_data()
        new_full_name = data["full_name"]

        try:
            user = await client_management_service.request_name_change(current_user.ID, new_full_name)
        except BotException as e:
            await message.answer(e.localized(lang))
            return

        await client_notification_service.notify_admins_name_change_request(
            user, new_full_name, user_id=user.ID,
        )

        await message.answer(_REQUEST_SENT.get(lang, _REQUEST_SENT["ru"]))
        await state.clear()

    return router
