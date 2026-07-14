from aiogram.types import Message

from bot.keyboards.admin.admin_main_menu_kb import start_admin_keyboard
from bot.keyboards.client.client_main_keyboard import start_client_keyboard
from bot.keyboards.client.help_kb import client_help_guide_kb


async def show_main_admin_menu(message: Message, full_name: str):
    await message.answer(f"Здравствуйте, {full_name}.\n\n"
                         "Это бот для учета клиентов и записей на прием.\n\n"
                         'Для ознакомления с функционалом нажмите "Справка".')

    await message.answer(text='Выберите вариант: ', reply_markup=start_admin_keyboard())


async def show_main_client_menu(message: Message, full_name: str):
    await message.answer(f"Здравствуйте, {full_name}.\n\n"
                        f'Это бот для учета записей на прием в стоматологию "Зуб Мудрости".\n'
                         f'Вы будете получать напоминания о предстоящих записях с возможностью подтвердить или отменить их.\n\n'
                         'Для ознакомления с функционалом нажмите "Помощь".')

    await message.answer(text='Выберите вариант: ', reply_markup=start_client_keyboard())

async def display_admin_help_msg(message: Message):
    text = ("Справочное меню.\n\n\n"
            "/client_managing:\n\n"
            "  1. Добавить клиента.\n"
            "  2. Клиенты - поиск по имени или номеру телефона, либо список "
            "всех клиентов; в карточке клиента доступны изменение ФИ/телефона "
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
    text = ("Меню помощи.\n\n\n"
            "📋 Управление записями:\n\n"
            "  1. Записаться на прием - выбор даты, времени и услуги для новой записи.\n"
            "  2. История записей - список всех ваших прошлых и предстоящих записей.\n"
            "  3. Управление записью - перенос времени или отмена уже созданной записи.\n\n"
            "О предстоящих записях бот присылает отдельные напоминания с "
            "кнопками подтверждения и отмены.\n\n\n"
            "/start - запуск бота.\n"
            "/help - помощь.\n"
            "/profile - личные данные.\n"
            "/price - прайс-лист")
    await message.answer(text=text, reply_markup=client_help_guide_kb())

async def display_client_help_guide_msg(message: Message) -> None:
    text = (
        "Как это работает:\n\n"
        "1️⃣ «📋 Управление записями» → «Записаться на приём».\n"
        "2️⃣ Выбираете врача, день и свободное время, коротко описываете причину визита.\n"
        "3️⃣ Заявка уходит в клинику: администратор подтверждает, отклоняет "
        "или предлагает другое время.\n"
        "4️⃣ Если предложено новое время — соглашаетесь или отклоняете прямо в чате.\n"
        "5️⃣ Когда запись подтверждена, бот пришлёт напоминания за 24ч и за 2ч "
        "до приёма с кнопками «Приду» / «Не приду».\n"
        "6️⃣ Перенести или отменить запись можно в «Управлении записями» в любой "
        "момент, кроме последнего часа перед приёмом."
    )
    await message.answer(text)

async def display_registration_guide_msg(message: Message) -> None:
    text = (
        "Как пройти регистрацию:\n\n"
        "[Открыли ссылку/QR клиники]\n"
        "        ↓\n"
        "   Бот просит контакт\n"
        "        ↓\n"
        " Жмите кнопку \"📱 Отправить контакт\"\n"
        "  (номер вручную НЕ вводите!)\n"
        "        ↓\n"
        "  Бот находит вашу карту\n"
        "     или заводит новую\n"
        "        ↓\n"
        "    Подтвердите ФИО\n"
        "        ↓\n"
        "       Готово ✅\n\n"
        "⚠️ Номер телефона отправляется ТОЛЬКО кнопкой \"📱 Отправить контакт\". "
        "Вручную вводить номер нельзя — это единственный поддерживаемый способ."
    )
    await message.answer(text)