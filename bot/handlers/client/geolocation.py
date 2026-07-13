from aiogram import F, Router
from aiogram.types import Message, FSInputFile, InputMediaPhoto
from bot.utils.role import RoleFilter


def create_price_geo_router():

    router = Router()

    router.message.filter(RoleFilter("client"))

    @router.message(F.text.in_({"/geo", "📍 Локация"}), RoleFilter("client"))
    async def geo_client(message: Message):
        media = [
            InputMediaPhoto(media=FSInputFile("data/location/location.png"), caption="https://yandex.uz/maps/-/CTBl4J6V\n"
                                                                                     "ул. Мирзо Улугбека 105/3 (вход со стороны дороги).\n"
                                                                                     'Ориентир: магазин "Чимган".')]
        await message.answer_media_group(media)




    return router