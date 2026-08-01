from aiogram import F, Router
from aiogram.types import Message, FSInputFile, InputMediaPhoto

from bot.config.clinic_instances import PRICE_LIST_BY_INSTANCE, PRICE_LIST_STUB_MESSAGE
from bot.utils.role import RoleFilter


def create_price_list_router(instance: str):

    router = Router()

    router.message.filter(RoleFilter("client"))

    @router.message(F.text.in_({"/price", "📋 Прайс-лист", "📋 Narxlar ro'yxati"}), RoleFilter("client"))
    async def price_client(message: Message):
        price_list = PRICE_LIST_BY_INSTANCE.get(instance)

        if price_list is None:
            await message.answer(PRICE_LIST_STUB_MESSAGE)
            return

        image_paths = price_list["image_paths"]
        media = [
            InputMediaPhoto(media=FSInputFile(path)) if index < len(image_paths) - 1
            else InputMediaPhoto(media=FSInputFile(path), caption=price_list["caption"])
            for index, path in enumerate(image_paths)
        ]
        await message.answer_media_group(media)



    return router