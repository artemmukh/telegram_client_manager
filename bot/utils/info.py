from aiogram.types import Message

from bot.keyboards.admin.admin_main_menu_kb import start_admin_keyboard
from bot.keyboards.client.client_main_keyboard import start_client_keyboard


async def show_main_admin_menu(message: Message, full_name: str):
    await message.answer(f"Здравствуйте, {full_name}.\n\n"
                         "Это бот для учета клиентов и записей на прием.\n\n"
                         'Для ознакомления с функционалом нажмите "Справка".')

    await message.answer(text='Выберите вариант: ', reply_markup=start_admin_keyboard())


async def show_main_client_menu(message: Message, full_name: str):
    await message.answer(f"Здравствуйте, {full_name}.\n\n"
                        f'Это бот для учета записей на прием в стоматологию "Зуб Мудрости".\n'
                         f'Вы будете получать напоминания о предстоящих записях с возможностью подтвердить или отменить их.\n\n'
                         'Для ознакомления с функционалом нажмите "Справка".')

    await message.answer(text='Выберите вариант: ', reply_markup=start_client_keyboard())

async def display_admin_help_msg(message: Message):
    text = ("Справочное меню.\n\n\n"
            "/client_managing:\n\n"
            "  1. Добавить клиента.\n"
            "  2. Клиенты - поиск по имени или номеру телефона, либо список "
            "всех клиентов; в карточке клиента доступны изменение ФИО/телефона "
            "и удаление.\n\n\n"
            "/record_managing:\n\n"
            "  1. Создать запись.\n"
            "  2. Записи - поиск по имени или номеру телефона, либо список "
            "всех записей; в карточке записи доступно редактирование и удаление.\n\n\n"
            "/start - запуск бота.\n"
            "/help - справка.\n"
            "/profile - личные данные.")
    await message.answer(text=text)

async def display_client_help_msg(message: Message):
    text = ("Справочное меню.\n\n\n"
            "📋 Управление записями:\n\n"
            "  1. Записаться на прием - выбор даты, времени и услуги для новой записи.\n"
            "  2. История записей - список всех ваших прошлых и предстоящих записей.\n"
            "  3. Управление записью - перенос времени или отмена уже созданной записи.\n\n"
            "О предстоящих записях бот присылает отдельные напоминания с "
            "кнопками подтверждения и отмены.\n\n\n"
            "/start - запуск бота.\n"
            "/help - справка.\n"
            "/profile - личные данные.\n"
            "/price - прайс-лист")
    await message.answer(text=text)