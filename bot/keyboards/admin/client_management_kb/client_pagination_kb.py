from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.utils.pagination import get_circular_page


def pagination_keyboard(
    mode: str, current_page: int, total_pages: int
) -> InlineKeyboardMarkup:
    """
    Клавиатура пагинации для листинга клиентов

    Args:
        mode: 'list' или 'search'
        current_page: текущая страница
        total_pages: общее количество страниц

    Returns:
        InlineKeyboardMarkup: клавиатура с кнопками навигации
    """
    builder = InlineKeyboardBuilder()

    if total_pages > 1:
        # Кнопки навигации с циклической поддержкой
        prev_page = get_circular_page(current_page, total_pages, "prev")
        next_page = get_circular_page(current_page, total_pages, "next")

        builder.button(
            text="⬅️",
            callback_data=f"page:{mode}:{prev_page}"
        )
        builder.button(
            text=f"{current_page} из {total_pages}",
            callback_data="noop"
        )
        builder.button(
            text="➡️",
            callback_data=f"page:{mode}:{next_page}"
        )
        builder.button(text="⬅️ К меню", callback_data="back_to_main_menu")
        builder.adjust(4)
    else:
        # Одна страница - показываем статус без навигации
        builder.button(
            text="Страница 1 из 1",
            callback_data="noop"
        )
        builder.button(text="⬅️ К меню", callback_data="back_to_main_menu")
        builder.adjust(2)

    return builder.as_markup()
