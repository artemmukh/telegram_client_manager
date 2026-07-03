from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.utils.role import RoleFilter


def create_cancel_router():

    router = Router()
    router.message.filter(RoleFilter("*"))
    router.callback_query.filter(RoleFilter("*"))

    @router.callback_query(F.data == "cancel", RoleFilter("*"))
    async def cancel(callback: CallbackQuery, state: FSMContext):
        await state.clear()

        await callback.message.edit_text(
            "Действие отменено.",
            reply_markup=None
        )

        await callback.answer('')


    return router