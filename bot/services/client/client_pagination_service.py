from dataclasses import dataclass
from math import ceil

from bot.exceptions.exceptions import PaginationError
from bot.models.user import User
from bot.repositories.user_repository import UserRepository
from bot.utils.pagination import CLIENTS_PER_PAGE


@dataclass
class PaginationResult:
    """Результат пагинированного запроса"""
    items: list[User]
    current_page: int
    total_pages: int
    total_count: int
    has_prev: bool
    has_next: bool


class ClientPaginationService:
    """Сервис пагинации для листинга клиентов"""

    def __init__(self, user_repository: UserRepository):
        self.user_repo = user_repository

    async def paginate_clients(
        self,
        mode: str,
        page: int,
        search_data: dict = None
    ) -> PaginationResult:
        """
        Получить страницу клиентов с метаданными пагинации

        Args:
            mode: 'list' - все клиенты, 'search' - результаты поиска
            page: номер страницы
            search_data: dict с 'full_name' для mode='search'

        Returns:
            PaginationResult с информацией о странице
        """
        if mode == "list":
            total_count = await self.user_repo.count_all_clients()
            items = await self.user_repo.get_clients_page(page, CLIENTS_PER_PAGE)
        elif mode == "search":
            if not search_data:
                search_data = {}
            full_name = search_data.get("full_name", "")
            total_count = await self.user_repo.count_clients_by_name(full_name)
            items = await self.user_repo.get_clients_by_name_page(
                full_name, page, CLIENTS_PER_PAGE
            )
        else:
            raise PaginationError(f"Неизвестный режим пагинации: {mode}")

        total_pages = ceil(total_count / CLIENTS_PER_PAGE) if total_count > 0 else 1

        # Зажим страницы в валидный диапазон
        page = max(1, min(page, total_pages))

        return PaginationResult(
            items=items,
            current_page=page,
            total_pages=total_pages,
            total_count=total_count,
            has_prev=page > 1,
            has_next=page < total_pages,
        )

    @staticmethod
    def format_clients_text(
        clients: list[User],
        current_page: int,
        total_pages: int,
        mode: str,
        total_count: int = 0
    ) -> str:
        """
        Форматирует текст списка клиентов

        Args:
            clients: список клиентов
            current_page: текущая страница
            total_pages: общее количество страниц
            mode: 'list' или 'search'
            total_count: общее количество клиентов

        Returns:
            str: отформатированный текст
        """
        if mode == "list":
            title = f"📋 Список всех клиентов ({current_page} из {total_pages}) | Всего: {total_count}"
        elif mode == "search":
            title = f"🔍 Результаты поиска ({current_page} из {total_pages}) | Всего: {total_count}"
        else:
            title = f"Клиенты ({current_page} из {total_pages})"

        lines = [title, ""]

        if not clients:
            lines.append("Клиентов не найдено")
            return "\n".join(lines)

        # Вычисляем глобальный стартовый номер
        start_index = (current_page - 1) * CLIENTS_PER_PAGE + 1

        # Нумеруем с глобального начального номера
        for index, user in enumerate(clients, start=start_index):
            if index > start_index:
                lines.append("")
            lines.append(f"{index}.")
            if user.ID is not None:
                lines.append(f"ID: {user.ID}")
            lines.append(f"ФИО: {user.full_name}")
            lines.append(f"Телефон: {user.phone}")
            if user.clinic_name:
                lines.append(f"Клиника: {user.clinic_name}")

        return "\n".join(lines)
