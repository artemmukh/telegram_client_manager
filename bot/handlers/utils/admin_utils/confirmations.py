from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.models.user import User

FIELDS = {
    "user_id": "ID клиента",
    "full_name": "ФИО",
    "phone": "Телефон",
}


def build_client_text(title: str, data: dict) -> str:
    lines = [title, ""]

    for key, caption in FIELDS.items():
        if key in data:
            lines.append(f"{caption}: {data[key]}")

    return "\n".join(lines)


def build_users_list_text(title: str, users: list[User]) -> str:
    lines = [title, ""]

    for index, user in enumerate(users, start=1):
        if index > 1:
            lines.append("")
        lines.append(f"{index}.")
        if user.ID is not None:
            lines.append(f"{FIELDS['user_id']}: {user.ID}")
        lines.append(f"{FIELDS['full_name']}: {user.full_name}")
        lines.append(f"{FIELDS['phone']}: {user.phone}")

    return "\n".join(lines)


async def show_confirmation(
    message: Message,
    state: FSMContext,
    reply_markup=None,
) -> None:
    data = await state.get_data()

    await message.answer(
        text=build_client_text(
            "Проверьте введенные данные:",
            data,
        ),
        reply_markup=reply_markup,
    )


async def show_success(
    callback: CallbackQuery,
    title: str,
    **kwargs,
) -> None:

    text = build_client_text(title, kwargs)

    await callback.message.edit_text(
        text=text,
        reply_markup=None,
    )


async def show_users(callback: CallbackQuery, title: str, users: list[User]):
    await callback.message.edit_text(
        text=build_users_list_text(title, users),
    )



