CLIENTS_PER_PAGE = 10


def parse_pagination_callback(callback_data: str) -> tuple[str, int]:
    """
    Парсит callback_data вида 'page:list:1' или 'page:search:2'
    Возвращает кортеж (mode, page_number)

    Args:
        callback_data: строка вида 'page:mode:page_num'

    Returns:
        tuple[str, int]: (mode, page_number)
    """
    parts = callback_data.split(":")
    if len(parts) != 3 or parts[0] != "page":
        raise ValueError(f"Invalid pagination callback: {callback_data}")

    mode = parts[1]  # 'list' или 'search'
    try:
        page_num = int(parts[2])
    except ValueError:
        raise ValueError(f"Invalid page number in callback: {callback_data}")

    if page_num < 1:
        page_num = 1

    return mode, page_num


def get_circular_page(page: int, total_pages: int, direction: str) -> int:
    """
    Циклическая навигация между страницами.
    Последняя страница -> next -> первая страница
    Первая страница -> prev -> последняя страница

    Args:
        page: текущая страница
        total_pages: общее количество страниц
        direction: 'next' или 'prev'

    Returns:
        int: номер новой страницы
    """
    if total_pages <= 1:
        return 1

    if direction == "next":
        if page >= total_pages:
            return 1
        return page + 1
    elif direction == "prev":
        if page <= 1:
            return total_pages
        return page - 1
    else:
        raise ValueError(f"Unknown direction: {direction}")
