from aiogram.types import Message

import bot.messages.common as msg
from bot.keyboards.admin.admin_main_menu_kb import start_admin_keyboard
from bot.keyboards.client.client_main_keyboard import start_client_keyboard


async def show_main_admin_menu(message: Message, full_name: str):
    await message.answer(msg.admin_greeting(full_name))

    await message.answer(text=msg.MAIN_ADMIN_MENU_CHOOSE_OPTION, reply_markup=start_admin_keyboard())


async def show_main_client_menu(message: Message, full_name: str, clinic_name: str):
    await message.answer(msg.client_greeting(full_name, clinic_name))

    await message.answer(text=msg.MAIN_CLIENT_MENU_CHOOSE_OPTION, reply_markup=start_client_keyboard())
