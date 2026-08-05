from aiogram.filters.callback_data import CallbackData


class SlotBlockTargetCB(CallbackData, prefix="sb_target"):
    """Выбор врача (или всей клиники) для блокировки слотов. 0 = вся клиника."""
    staff_id: int = 0


class SlotBlockConfirmCB(CallbackData, prefix="sb_confirm"):
    """Подтверждение/отмена создания блокировки: action - 'create' или 'cancel'.

    Используется как для шага с конфликтующими записями, так и для обычного
    подтверждения (когда конфликтов нет) - в обоих случаях набор действий
    одинаков.
    """
    action: str


class SlotBlockListCB(CallbackData, prefix="sb_list"):
    """Навигация по страницам списка активных блокировок."""
    page: int


class SlotBlockCancelCB(CallbackData, prefix="sb_cancel"):
    """Отмена активной блокировки: step - 'confirm' (запрос подтверждения)
    или 'execute' (собственно отмена)."""
    block_id: int
    step: str
