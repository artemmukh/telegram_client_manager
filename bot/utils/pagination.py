CLIENTS_PER_PAGE = 10
APPOINTMENTS_PER_PAGE = 10


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
