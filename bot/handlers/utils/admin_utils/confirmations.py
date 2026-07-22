from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.admin.client_management_kb.client_main_menu_kb import back_to_menu_kb

GENDER_LABELS = {"male": "Мужской", "female": "Женский"}

FIELDS = {
    "user_id": "ID клиента",
    "full_name": "ФИ",
    "birth_date": "Дата рождения",
    "gender": "Пол",
    "phone": "Телефон",
    "clinic_name": "Клиника"
}


def build_client_text(title: str, data: dict) -> str:
    lines = [title, ""]

    for key, caption in FIELDS.items():
        if key not in data:
            continue

        value = GENDER_LABELS.get(data[key], data[key]) if key == "gender" else data[key]
        lines.append(f"{caption}: {value}")

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

    await callback_query.answer('')
    await callback_query.message.edit_text(
        text=text, reply_markup=back_to_menu_kb()
    )





