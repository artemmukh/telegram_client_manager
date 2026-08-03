from aiogram import F, Router
from aiogram.types import Message, FSInputFile, InputMediaPhoto

from bot.config.clinic_instances import LOCATION_BY_INSTANCE, LOCATION_STUB_MESSAGE
from bot.models.user import User
from bot.utils.role import RoleFilter


def create_price_geo_router(instance: str):

    router = Router()

    router.message.filter(RoleFilter("client"))

    @router.message(F.text.in_({"/geo", "📍 Локация", "📍 Manzil"}), RoleFilter("client"))
    async def geo_client(message: Message, current_user: User):
        lang = current_user.language
        location = LOCATION_BY_INSTANCE.get(instance)

        if location is None:
            await message.answer(LOCATION_STUB_MESSAGE.get(lang, LOCATION_STUB_MESSAGE["ru"]))
            return

        caption = location["caption"].get(lang, location["caption"]["ru"])
        media = [InputMediaPhoto(media=FSInputFile(location["image_path"]), caption=caption)]
        await message.answer_media_group(media)




    return router