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


def client_browser_back_to_search_kb() -> InlineKeyboardMarkup:
    """Единственная кнопка "к меню поиска" - для экранов ввода (ФИ/телефон)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ К меню поиска", callback_data="browse_clients")
    return builder.as_markup()


def client_browser_cancel_edit_kb(client_id: int, mode: str, page: int) -> InlineKeyboardMarkup:
    """Единственная кнопка "отменить" - возврат к карточке клиента без изменений."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="❌ Отменить",
        callback_data=ClientActionCB(action="cancel_edit", client_id=client_id, mode=mode, page=page).pack(),
    )
    return builder.as_markup()


def client_browser_search_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text="👤 Поиск по имени", callback_data="cl_search_name")
    builder.button(text="📞 Поиск по номеру", callback_data="cl_search_phone")
    builder.button(text="👥 Показать всех клиентов", callback_data="cl_search_all")
    builder.button(text="⬅️ К меню", callback_data="back_to_main_menu")

    builder.adjust(2, 1, 1)
    return builder.as_markup()


def client_browser_confirm_name_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Подтвердить", callback_data="cl_approve_search")
    builder.button(text="📝 Изменить ФИ", callback_data="cl_edit_search_name")
    builder.button(text="⬅️ К меню поиска", callback_data="browse_clients")

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def client_browser_confirm_phone_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ Подтвердить", callback_data="cl_approve_search")
    builder.button(text="📲 Изменить номер", callback_data="cl_edit_search_phone")
    builder.button(text="⬅️ К меню поиска", callback_data="browse_clients")

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def client_list_kb(
    items: list[User],
    mode: str,
    current_page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
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

        builder.button(text=f"{current_page} из {total_pages}", callback_data="noop")
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
        builder.button(text="Страница 1 из 1", callback_data="noop")
        rows += [1]

    builder.button(text="⬅️ К меню поиска", callback_data="browse_clients")
    rows += [1]

    builder.adjust(*rows)
    return builder.as_markup()


def client_card_kb(client_id: int, mode: str, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="➕Записать на приём",
        callback_data=ClientActionCB(action="new_appointment", client_id=client_id, mode=mode, page=page).pack(),
    )

    builder.button(
        text="✏️ Изменить ФИ",
        callback_data=ClientActionCB(action="edit_name", client_id=client_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text="📞 Изменить телефон",
        callback_data=ClientActionCB(action="edit_phone", client_id=client_id, mode=mode, page=page).pack(),
    )

    if mode == "direct":
        # Карточка открыта напрямую (поиск по номеру всегда даёт 0 или 1
        # совпадение) - списка, куда возвращаться, не существует.
        builder.button(text="⬅️ К меню поиска", callback_data="browse_clients")
    else:
        builder.button(
            text="⬅️ Назад к списку",
            callback_data=ClientPageCB(mode=mode, page=page).pack(),
        )

    builder.adjust(2, 1)
    return builder.as_markup()


def client_delete_confirm_kb(client_id: int, mode: str, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Да, удалить",
        callback_data=ClientActionCB(action="confirm_delete", client_id=client_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text="❌ Отмена",
        callback_data=ClientActionCB(action="cancel_delete", client_id=client_id, mode=mode, page=page).pack(),
    )

    builder.adjust(1, 1)
    return builder.as_markup()


def client_confirm_new_name_kb(client_id: int, mode: str, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить",
        callback_data=ClientActionCB(action="approve_new_name", client_id=client_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text="📝 Ввести заново",
        callback_data=ClientActionCB(action="retry_new_name", client_id=client_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text="❌ Отменить",
        callback_data=ClientActionCB(action="cancel_edit", client_id=client_id, mode=mode, page=page).pack(),
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()


def client_confirm_new_phone_kb(client_id: int, mode: str, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Подтвердить",
        callback_data=ClientActionCB(action="approve_new_phone", client_id=client_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text="📲 Ввести заново",
        callback_data=ClientActionCB(action="retry_new_phone", client_id=client_id, mode=mode, page=page).pack(),
    )
    builder.button(
        text="❌ Отменить",
        callback_data=ClientActionCB(action="cancel_edit", client_id=client_id, mode=mode, page=page).pack(),
    )

    builder.adjust(1, 1, 1)
    return builder.as_markup()
