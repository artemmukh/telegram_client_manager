from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.admin.client_management_kb.client_main_menu_kb import back_to_menu_kb

GENDER_LABELS = {
    "ru": {"male": "Мужской", "female": "Женский"},
    "uz": {"male": "Erkak", "female": "Ayol"},
}

FIELDS = {
    "ru": {
        "user_id": "ID клиента",
        "full_name": "ФИ",
        "birth_date": "Дата рождения",
        "gender": "Пол",
        "phone": "Телефон",
        "clinic_name": "Клиника"
    },
    "uz": {
        "user_id": "Mijoz ID",
        "full_name": "F.I.Sh.",
        "birth_date": "Tug'ilgan sana",
        "gender": "Jinsi",
        "phone": "Telefon",
        "clinic_name": "Klinika"
    },
}

CONFIRM_TITLE = {
    "ru": "Проверьте введенные данные:",
    "uz": "Kiritilgan ma'lumotlarni tekshiring:",
}


def build_client_text(title: str, data: dict, lang: str = "ru") -> str:
    fields = FIELDS.get(lang, FIELDS["ru"])
    gender_labels = GENDER_LABELS.get(lang, GENDER_LABELS["ru"])
    lines = [title, ""]

    for key, caption in fields.items():
        if key not in data:
            continue

        value = gender_labels.get(data[key], data[key]) if key == "gender" else data[key]
        lines.append(f"{caption}: {value}")

    return "\n".join(lines)


async def show_confirmation(
    message: Message,
    state: FSMContext,
    reply_markup=None,
    lang: str = "ru",
) -> None:
    data = await state.get_data()

    await message.answer(
        text=build_client_text(
            CONFIRM_TITLE.get(lang, CONFIRM_TITLE["ru"]),
            data,
            lang,
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





