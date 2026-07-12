from aiogram import F, Router
from aiogram.types import Message, FSInputFile, InputMediaPhoto
from bot.utils.role import RoleFilter


def create_price_geo_router():

    router = Router()

    router.message.filter(RoleFilter("client"))

    @router.message(F.text.in_({"/geo", "📍 Локация"}), RoleFilter("client"))
    async def geo_client(message: Message):
        pass




    return router