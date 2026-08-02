from dataclasses import dataclass
from math import ceil

from bot.exceptions.exceptions import PaginationError
from bot.models.user import User
from bot.repositories.user_repository import UserRepository
from bot.utils.pagination import CLIENTS_PER_PAGE

_UNKNOWN_PAGINATION_MODE_MESSAGE = {
    "ru": "Неизвестный режим пагинации: {mode}",
    "uz": "Noma'lum sahifalash rejimi: {mode}",
}


@dataclass
class PaginationResult:
    """Результат пагинированного запроса"""
    items: list[User]
    current_page: int
    total_pages: int
    total_count: int


class ClientPaginationService:
    """Сервис пагинации для листинга клиентов"""

    def __init__(self, user_repository: UserRepository):
        self.user_repo = user_repository

    async def paginate_clients(
        self,
        mode: str,
        page: int,
        clinic_id: int,
        search_data: dict = None
    ) -> PaginationResult:
        """
        Получить страницу клиентов с метаданными пагинации

        Args:
            mode: 'list' - все клиенты, 'search' - результаты поиска
            page: номер страницы
            clinic_id: клиника, к которой скоупится выборка
            search_data: dict с 'full_name' для mode='search'

        Returns:
            PaginationResult с информацией о странице
        """
        if mode == "list":
            total_count = await self.user_repo.count_clients_in_clinic(clinic_id)
            items = await self.user_repo.get_clients_page_in_clinic(clinic_id, page, CLIENTS_PER_PAGE)
        elif mode == "search":
            if not search_data:
                search_data = {}
            full_name = search_data.get("full_name", "")
            total_count = await self.user_repo.count_clients_by_name_in_clinic(full_name, clinic_id)
            items = await self.user_repo.get_clients_by_name_page_in_clinic(
                full_name, clinic_id, page, CLIENTS_PER_PAGE
            )
        else:
            raise PaginationError({
                "ru": _UNKNOWN_PAGINATION_MODE_MESSAGE["ru"].format(mode=mode),
                "uz": _UNKNOWN_PAGINATION_MODE_MESSAGE["uz"].format(mode=mode),
            })

        total_pages = ceil(total_count / CLIENTS_PER_PAGE) if total_count > 0 else 1

        # Зажим страницы в валидный диапазон
        page = max(1, min(page, total_pages))

        return PaginationResult(
            items=items,
            current_page=page,
            total_pages=total_pages,
            total_count=total_count,
        )
