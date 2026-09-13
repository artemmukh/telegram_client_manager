from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ReplyParameters


class TelegramNotifier:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup=None,
        reply_to_message_id: int | None = None,
    ) -> int:
        reply_parameters = None
        if reply_to_message_id is not None:
            reply_parameters = ReplyParameters(
                message_id=reply_to_message_id,
                allow_sending_without_reply=True,
            )

        sent_message = await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            reply_parameters=reply_parameters,
        )

        return sent_message.message_id

    async def try_edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup=None,
    ) -> bool:
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return True
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return True
            return False

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup=None,
    ) -> None:
        await self.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
        )
