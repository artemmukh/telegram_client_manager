from aiogram import F, Router
from aiogram.types import Message, FSInputFile, InputMediaPhoto
from bot.utils.role import RoleFilter


def create_price_list_router():

    router = Router()

    router.message.filter(RoleFilter("client"))

    @router.message(F.text.in_({"/price", "📋 Прайс-лист"}), RoleFilter("client"))
    async def help_client(message: Message):
        media = [
            InputMediaPhoto(media=FSInputFile("data/price_list/rus_1pg.png")),
            InputMediaPhoto(media=FSInputFile("data/price_list/rus_2pg.png"), caption="Прайс лист оказываемых услуг.")
        ]
        await message.answer_media_group(media)



    return router