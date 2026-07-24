from aiogram import F, Router
from aiogram.types import Message, FSInputFile, InputMediaPhoto

from bot.config.clinic_instances import LOCATION_BY_INSTANCE, LOCATION_STUB_MESSAGE
from bot.utils.role import RoleFilter


def create_price_geo_router(instance: str):

    router = Router()

    router.message.filter(RoleFilter("client"))

    @router.message(F.text.in_({"/geo", "📍 Локация"}), RoleFilter("client"))
    async def geo_client(message: Message):
        location = LOCATION_BY_INSTANCE.get(instance)

        if location is None:
            await message.answer(LOCATION_STUB_MESSAGE)
            return

        media = [InputMediaPhoto(media=FSInputFile(location["image_path"]), caption=location["caption"])]
        await message.answer_media_group(media)




    return router