from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

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
