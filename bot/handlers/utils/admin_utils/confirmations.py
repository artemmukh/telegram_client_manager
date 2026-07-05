from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.admin.client_management_kb.client_main_menu_kb import back_to_menu_kb
from bot.models.user import User

FIELDS = {
    "user_id": "ID клиента",
    "full_name": "ФИО",
    "phone": "Телефон",
    "clinic_name": "Клиника"
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
        lines.append(f"{FIELDS['clinic_name']}: {user.clinic_name}")

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
    callback_query: CallbackQuery,
    title: str,
    **kwargs,
) -> None:

    text = build_client_text(title, kwargs)

    await callback_query.message.edit_text(
        text=text, reply_markup=back_to_menu_kb()
    )



async def show_all_clients(callback_query: CallbackQuery, title: str, users: list[User]):
    await callback_query.message.edit_text(
        text=build_users_list_text(title, users), reply_markup=back_to_menu_kb()
    )

async def show_clients_one_be_one(
    callback: CallbackQuery,
    users: list[User],
    keyboard_factory=None,
):
    for user in users:
        markup = None


        if keyboard_factory:
            markup = keyboard_factory(user.ID)

        await callback.message.answer(
            text=build_client_text(
                "Клиент",
                {
                    "user_id": user.ID,
                    "full_name": user.full_name,
                    "phone": user.phone,
                    "clinic_name": user.clinic_name,
                },
            ),
            reply_markup=markup,
        )






