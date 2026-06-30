from aiogram.types import Message

from bot.keyboards.inline_reply_admin_keyboards import  start_admin_keyboard
from bot.keyboards.inline_reply_client_keyboard import start_client_keyboard


async def show_main_admin_menu(message: Message):
    await message.answer(f"Здравствуйте {message.from_user.first_name}.\n\n"
                         "Это бот для учета клиентов. С помощью ручного или голосового ввода с ИИ расшифровкой ведется учет клиентской базы.\n\n"
                         'Для ознакомления с функционалом нажмите "Справка".')

    await message.answer(text='Выберите вариант: ', reply_markup=start_admin_keyboard())


async def show_main_client_menu(message: Message):
    await message.answer(f"Здравствуйте {message.from_user.first_name}.\n\n"
                        f'Это бот для учета записей на прием в стоматологию "Зуб Мудрости".\n'
                         f'Вы можете просматривать историю записей, записать на прием и отслеживать его, получая напоминания.\n\n'
                         'Для ознакомления с функционалом нажмите "Справка".')

    await message.answer(text='Выберите вариант: ', reply_markup=start_client_keyboard())

async def display_admin_help_msg(message: Message):
    text = ("Справочное меню.\n\n\n"
            "/client_managing:\n\n"
            "  1. Создание нового клиента.\n"
            "  2. Удаление клиента.\n"
            "  3. Поиск клиента.\n"
            "  4. Обновления данных клиента.\n\n\n"
            "/record_managing:\n\n"
            "1. Создать запись клиента.\n"
            "2. Удалить запись клиента.\n"
            "3. Поиск записи клиента.\n"
            "4. Изменить запись клиента.\n\n\n"
            "/start - запуск бота.\n"
            "/help - справка.\n"
            "/profile - личные данные.")
    await message.answer(text=text)

async def display_client_help_msg(message: Message):
    text = ("Справочное меню.\n\n\n"
            "/create_an_appointment:\n\n"
            "  1. Записаться на прием.\n\n\n"
            "/history:\n\n"
            "1. Просмотр последних записей.\n\n\n"
            "/start - запуск бота.\n"
            "/help - справка.\n"
            "/profile - личные данные.")
    await message.answer(text=text)