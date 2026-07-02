from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

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
    await callback.message.edit_text(
        text=build_client_text(title, kwargs),
        reply_markup=None,
    )



