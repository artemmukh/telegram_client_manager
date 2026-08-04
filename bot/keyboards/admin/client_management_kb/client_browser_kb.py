from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.admin.client_management_kb.client_browser_cb import (
    ClientActionCB,
    ClientCardCB,
    ClientPageCB,
)
from bot.handlers.utils.admin_utils.client_browser_helpers import build_client_button_text
from bot.models.user import User
from bot.utils.pagination import get_circular_page


_TEXTS = {
    "ru": {
        "back_to_search_menu": "⬅️ К меню поиска",
        "cancel": "❌ Отменить",
        "search_by_name": "👤 Поиск по имени",
        "search_by_phone": "📞 Поиск по номеру",
        "show_all_clients": "👥 Показать всех клиентов",
        "back_to_menu": "⬅️ К меню",
        "confirm": "✅ Подтвердить",
        "edit_full_name": "📝 Изменить ФИ",
        "edit_phone": "📲 Изменить номер",
        "page_of": "{page} из {total}",
        "page_1_of_1": "Страница 1 из 1",
        "new_appointment": "➕Записать на приём",
        "view_appointments": "📋 Посмотреть записи",
        "edit_full_name_card": "✏️ Изменить ФИ",
        "edit_phone_card": "📞 Изменить телефон",
        "back_to_list": "⬅️ Назад к списку",
        "confirm_delete": "✅ Да, удалить",
        "confirm_unlink": "✅ Да, отвязать",
        "cancel_delete": "❌ Отмена",
        "retry_name": "📝 Ввести заново",
        "retry_phone": "📲 Ввести заново",
    },
    "uz": {
        "back_to_search_menu": "⬅️ Qidiruv menyusiga",
        "cancel": "❌ Bekor qilish",
        "search_by_name": "👤 Ism bo'yicha qidirish",
        "search_by_phone": "📞 Raqam bo'yicha qidirish",
        "show_all_clients": "👥 Barcha mijozlarni ko'rsatish",
        "back_to_menu": "⬅️ Menyuga",
        "confirm": "✅ Tasdiqlash",
        "edit_full_name": "📝 F.I.Sh.ni o'zgartirish",
        "edit_phone": "📲 Raqamni o'zgartirish",
        "page_of": "{page} / {total}",
        "page_1_of_1": "1 / 1 sahifa",
        "new_appointment": "➕Qabulga yozish",
        "view_appointments": "📋 Yozuvlarni ko'rish",
        "edit_full_name_card": "✏️ F.I.Sh.ni o'zgartirish",
        "edit_phone_card": "📞 Telefonni o'zgartirish",
        "back_to_list": "⬅️ Ro'yxatga qaytish",
        "confirm_delete": "✅ Ha, o'chirish",
        "confirm_unlink": "✅ Ha, uzish",
        "cancel_delete": "❌ Bekor qilish",
        "retry_name": "📝 Qayta kiritish",
        "retry_phone": "📲 Qayta kiritish",
    },
}


def _t(lang: str) -> dict:
    return _TEXTS.get(lang, _TEXTS["ru"])


def client_browser_back_to_search_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    """Единственная кнопка "к меню поиска" - для экранов ввода (ФИ/телефон)."""
    builder = InlineKeyboardBuilder()
    builder.button(text=_t(lang)["back_to_search_menu"], callback_data="browse_clients")
    return builder.as_markup()


def client_browser_cancel_edit_kb(client_id: int, mode: str, page: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """Единственная кнопка "отменить" - возврат к карточке клиента без изменений."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_t(lang)["cancel"],
        callback_data=ClientActionCB(action="cancel_edit", client_id=client_id, mode=mode, page=page).pack(),
    )
    return builder.as_markup()


def client_browser_search_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    texts = _t(lang)
    builder = InlineKeyboardBuilder()

    builder.button(text=texts["search_by_name"], callback_data="cl_search_name")
    builder.button(text=texts["search_by_phone"], callback_data="cl_search_phone")
    builder.button(text=texts["show_all_clients"], callback_data="cl_search_all")
    builder.button(text=texts["back_to_menu"], callback_data="back_to_main_menu")

    builder.adjust(2, 1, 1)
    return builder.as_markup()


def client_browser_confirm_name_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    texts = _t(lang)
    builder = InlineKeyboardBuilder()

    builder.button(text=texts["confirm"], callback_data="cl_approve_search")
    builder.button(text=texts["edit_full_name"], callback_data="cl_edit_search_name")
    builder.button(text=texts["back_to_search_menu"], callback_data="browse_clients")

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def client_browser_confirm_phone_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    texts = _t(lang)
    builder = InlineKeyboardBuilder()

    builder.button(text=texts["confirm"], callback_data="cl_approve_search")
    builder.button(text=texts["edit_phone"], callback_data="cl_edit_search_phone")
    builder.button(text=texts["back_to_search_menu"], callback_data="browse_clients")

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def client_list_kb(
    items: list[User],
    mode: str,
    current_page: int,
    total_pages: int,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    texts = _t(lang)
    builder = InlineKeyboardBuilder()

    for user in items:
        builder.button(
            text=build_client_button_text(user),
            callback_data=ClientCardCB(client_id=user.ID, mode=mode, page=current_page).pack(),
        )

    rows = [1] * len(items)

    if total_pages > 1:
        prev_page = get_circular_page(current_page, total_pages, "prev")
        next_page = get_circular_page(current_page, total_pages, "next")

        builder.button(text=texts["page_of"].format(page=current_page, total=total_pages), callback_data="noop")
        builder.button(
            text="⬅️",
            callback_data=ClientPageCB(mode=mode, page=prev_page).pack(),
        )
        builder.button(
            text="➡️",
            callback_data=ClientPageCB(mode=mode, page=next_page).pack(),
        )
        rows += [1, 2]
    else:
        builder.button(text=texts["page_1_of_1"], callback_data="noop")
        rows += [1]

    builder.button(text=texts["back_to_search_menu"], callback_data="browse_clients")
    rows += [1]

    builder.adjust(*rows)
    return builder.as_markup()


def client_card_kb(client_id: int, mode: str, page: int, lang: str = "ru") -> InlineKeyboardMarkup:
    texts = _t(lang)
    builder = InlineKeyboardBuilder()

    builder.button(
        text=texts["new_appointment"],
        callback_data=ClientActionCB(action="new_appointment", client_id=client_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text=texts["view_appointments"],
        callback_data=ClientActionCB(action="view_appointments", client_id=client_id, mode=mode, page=page).pack(),
    )

    builder.button(
        text=texts["edit_full_name_card"],
        callback_data=ClientActionCB(action="edit_name", client_id=client_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text=texts["edit_phone_card"],
        callback_data=ClientActionCB(action="edit_phone", client_id=client_id, mode=mode, page=page).pack(),
    )

    if mode == "direct":
        # Карточка открыта напрямую (поиск по номеру всегда даёт 0 или 1
        # совпадение) - списка, куда возвращаться, не существует.
        builder.button(text=texts["back_to_search_menu"], callback_data="browse_clients")
    else:
        builder.button(
            text=texts["back_to_list"],
            callback_data=ClientPageCB(mode=mode, page=page).pack(),
        )

    builder.adjust(2, 2, 1)
    return builder.as_markup()


def client_delete_confirm_kb(
    client_id: int, mode: str, page: int, is_last_clinic: bool = True, lang: str = "ru",
) -> InlineKeyboardMarkup:
    texts = _t(lang)
    builder = InlineKeyboardBuilder()

    builder.button(
        text=texts["confirm_delete"] if is_last_clinic else texts["confirm_unlink"],
        callback_data=ClientActionCB(action="confirm_delete", client_id=client_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text=texts["cancel_delete"],
        callback_data=ClientActionCB(action="cancel_delete", client_id=client_id, mode=mode, page=page).pack(),
    )

    builder.adjust(1, 1)
    return builder.as_markup()


def client_confirm_new_name_kb(client_id: int, mode: str, page: int, lang: str = "ru") -> InlineKeyboardMarkup:
    texts = _t(lang)
    builder = InlineKeyboardBuilder()

    builder.button(
        text=texts["confirm"],
        callback_data=ClientActionCB(action="approve_new_name", client_id=client_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text=texts["retry_name"],
        callback_data=ClientActionCB(action="retry_new_name", client_id=client_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text=texts["cancel"],
        callback_data=ClientActionCB(action="cancel_edit", client_id=client_id, mode=mode, page=page).pack(),
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def client_confirm_new_phone_kb(client_id: int, mode: str, page: int, lang: str = "ru") -> InlineKeyboardMarkup:
    texts = _t(lang)
    builder = InlineKeyboardBuilder()

    builder.button(
        text=texts["confirm"],
        callback_data=ClientActionCB(action="approve_new_phone", client_id=client_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text=texts["retry_phone"],
        callback_data=ClientActionCB(action="retry_new_phone", client_id=client_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text=texts["cancel"],
        callback_data=ClientActionCB(action="cancel_edit", client_id=client_id, mode=mode, page=page).pack(),
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()
