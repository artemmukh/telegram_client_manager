from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.models.user import User
from bot.utils.tools import format_phone_short


def build_client_button_text(user: User) -> str:
    return f"👤 {user.full_name} · {format_phone_short(user.phone)}"


def build_client_card_text(user: User) -> str:
    lines = [
        f"👤 {user.full_name}",
        f"📞 {user.phone}",
    ]
    if user.clinic_name:
        lines.append(f"🏥 Клиника: {user.clinic_name}")
    return "\n".join(lines)


async def remember_tracked_message(state: FSMContext, message: Message) -> None:
    """Запомнить сообщение, которое сейчас служит "экраном" списка/карточки."""
    await state.update_data(
        card_chat_id=message.chat.id,
        card_message_id=message.message_id,
    )


async def edit_tracked_message(
    bot: Bot,
    state: FSMContext,
    text: str,
    reply_markup=None,
) -> None:
    """Отредактировать сохранённое сообщение-"экран" в ответ на текстовый ввод юзера.

    Используется там, где событие пришло как Message (текст от юзера), а не
    CallbackQuery, поэтому напрямую отредактировать "то самое" сообщение бота
    можно только зная его chat_id/message_id, сохранённые заранее.
    """
    data = await state.get_data()
    chat_id = data.get("card_chat_id")
    message_id = data.get("card_message_id")

    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_markup=reply_markup,
    )


async def render_client_card(
    cl_mng, callback_query: CallbackQuery, state: FSMContext, client_id: int, mode: str, page: int, clinic_id: int,
) -> bool:
    from bot.keyboards.admin.client_management_kb.client_browser_kb import client_card_kb

    user = await cl_mng.get_client_by_id(client_id, clinic_id)
    if user is None:
        await callback_query.answer("Клиент не найден.", show_alert=True)
        return False

    await callback_query.answer('')
    await callback_query.message.edit_text(
        build_client_card_text(user),
        reply_markup=client_card_kb(client_id, mode, page),
    )
    await remember_tracked_message(state, callback_query.message)
    return True
