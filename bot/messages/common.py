_ADMIN_HELP = {
    "ru": ("Справочное меню.\n\n\n"
        "👥 Управление клиентами:\n\n"
        "  1. /create_client - добавить клиента.\n"
        "  2. /clients - поиск по имени или номеру телефона, либо список "
        "всех клиентов; в карточке клиента доступны изменение ФИ/телефона "
        "и удаление.\n\n\n"
        "📋 Управление записями:\n\n"
        "  1. /create_appointment - создать запись.\n"
        "  2. /appointments - поиск по имени или номеру телефона, либо список "
        "всех записей; в карточке записи доступно редактирование и удаление.\n"
        "  3. /calendar - календарь записей по дням.\n\n\n"
        "/start - запуск бота.\n"
        "/help - справка.\n"
        "/profile - личные данные."),
    "uz": ("Ma'lumot menyusi.\n\n\n"
        "👥 Mijozlarni boshqarish:\n\n"
        "  1. /create_client - mijoz qo'shish.\n"
        "  2. /clients - ism yoki telefon raqami bo'yicha qidirish, yoki barcha "
        "mijozlar ro'yxati; mijoz kartasida F.I.Sh./telefonni o'zgartirish "
        "va o'chirish mavjud.\n\n\n"
        "📋 Qabullarni boshqarish:\n\n"
        "  1. /create_appointment - qabul yaratish.\n"
        "  2. /appointments - ism yoki telefon raqami bo'yicha qidirish, yoki barcha "
        "qabullar ro'yxati; qabul kartasida tahrirlash va o'chirish mavjud.\n"
        "  3. /calendar - kunlar bo'yicha qabullar kalendari.\n\n\n"
        "/start - botni ishga tushirish.\n"
        "/help - ma'lumot.\n"
        "/profile - shaxsiy ma'lumotlar."),
}

_CLIENT_HELP = {
    "ru": ("Меню помощи.\n\n\n"
        "📋 Управление записями:\n\n"
        "  1. /book - записаться на прием: выбор даты, времени и услуги для новой записи.\n"
        "  2. /history - история записей: список всех ваших прошлых и предстоящих записей.\n"
        "  3. /appointments - управление записью: перенос времени или отмена уже созданной записи.\n\n"
        "О предстоящих записях бот присылает отдельные напоминания с "
        "кнопками подтверждения и отмены.\n\n\n"
        "/start - запуск бота.\n"
        "/help - помощь.\n"
        "/profile - личные данные.\n"
        "/price - прайс-лист.\n"
        "/geo - адрес клиники"),
    "uz": ("Yordam menyusi.\n\n\n"
        "📋 Qabullarni boshqarish:\n\n"
        "  1. /book - qabulga yozilish: yangi qabul uchun sana, vaqt va xizmatni tanlash.\n"
        "  2. /history - qabullar tarixi: barcha o'tgan va kelayotgan qabullaringiz ro'yxati.\n"
        "  3. /appointments - qabulni boshqarish: yaratilgan qabul vaqtini ko'chirish yoki bekor qilish.\n\n"
        "Kelayotgan qabullar haqida bot tasdiqlash va bekor qilish tugmalari bilan "
        "alohida eslatmalar yuboradi.\n\n\n"
        "/start - botni ishga tushirish.\n"
        "/help - yordam.\n"
        "/profile - shaxsiy ma'lumotlar.\n"
        "/price - narxlar ro'yxati.\n"
        "/geo - klinika manzili"),
}

_CLIENT_HELP_GUIDE = {
    "ru": (
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
        "\n\n Если у вас возникли трудности или вы хотите что-то предложить, напишите пожалуйста @lidok_crm_bot_support"
    ),
    "uz": (
        "Bu qanday ishlaydi:\n\n"
        "1️⃣ «📋 Qabullarni boshqarish» → «Qabulga yozilish».\n"
        "2️⃣ Shifokor, kun va bo'sh vaqtni tanlaysiz, tashrif sababini qisqacha yozasiz.\n"
        "3️⃣ Ariza klinikaga yuboriladi: administrator tasdiqlaydi, rad etadi "
        "yoki boshqa vaqt taklif qiladi.\n"
        "4️⃣ Agar yangi vaqt taklif qilingan bo'lsa — chatda to'g'ridan-to'g'ri rozi bo'lasiz yoki rad etasiz.\n"
        "5️⃣ Qabul tasdiqlangach, bot qabuldan 24 soat va 2 soat oldin «Boraman» / «Bormayman» "
        "tugmalari bilan eslatmalar yuboradi.\n"
        "6️⃣ Qabulni ko'chirish yoki bekor qilishni «Qabullarni boshqarish»da istalgan "
        "vaqtda, qabuldan oldingi so'nggi soatdan tashqari, amalga oshirish mumkin."
        "\n\n Agar qiyinchiliklarga duch kelsangiz yoki biror narsa taklif qilmoqchi bo'lsangiz, iltimos @lidok_crm_bot_support ga yozing"
    ),
}

_REGISTRATION_GUIDE = {
    "ru": (
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
    ),
    "uz": (
        "Ro'yxatdan qanday o'tish kerak:\n\n"
        "[Klinikaning havolasi/QR-kodi ochildi]\n"
        "        ↓\n"
        "   Bot kontaktingizni so'raydi\n"
        "        ↓\n"
        " \"📱 Kontaktni yuborish\" tugmasini bosing\n"
        "  (raqamni qo'lda KIRITMANG!)\n"
        "        ↓\n"
        "  Bot sizning kartangizni topadi\n"
        "     yoki yangisini ochadi\n"
        "        ↓\n"
        "    F.I.Sh.ni tasdiqlang\n"
        "        ↓\n"
        "       Tayyor ✅\n\n"
        "⚠️ Telefon raqami FAQAT \"📱 Kontaktni yuborish\" tugmasi orqali yuboriladi. "
        "Raqamni qo'lda kiritish mumkin emas — bu yagona qo'llab-quvvatlanadigan usul."
    ),
}

_MAIN_ADMIN_MENU_CHOOSE_OPTION = {
    "ru": "Выберите вариант: ",
    "uz": "Variantni tanlang: ",
}

_MAIN_CLIENT_MENU_CHOOSE_OPTION = {
    "ru": "Выберите вариант: ",
    "uz": "Variantni tanlang: ",
}

CHOOSE_LANGUAGE_PROMPT = "Выберите язык / Tilni tanlang:"

INVALID_CLINIC_TOKEN = (
    "QR-код или пригласительная ссылка недействительна. Обратитесь в клинику.\n"
    "QR-kod yoki taklif havolasi yaroqsiz. Klinikaga murojaat qiling."
)

_REGISTRATION_INTRO = {
    "ru": "Пройдите регистрацию для дальнейшего взаимодействия.",
    "uz": "Davom etish uchun ro'yxatdan o'ting.",
}

_SEND_CONTACT_PROMPT = {
    "ru": "Отправьте ваш контакт: ",
    "uz": "Kontaktingizni yuboring: ",
}

_ALREADY_REGISTERED = {
    "ru": "Вы уже зарегистрированы.",
    "uz": "Siz allaqachon ro'yxatdan o'tgansiz.",
}

_PHONE_ALREADY_LINKED = {
    "ru": "Этот номер телефона уже привязан к другому аккаунту Telegram.\nОбратитесь в клинику.",
    "uz": "Bu telefon raqami boshqa Telegram akkauntiga bog'langan.\nKlinikaga murojaat qiling.",
}

_CONTACT_OWNERSHIP_MISMATCH = {
    "ru": "Похоже, вы отправили чужой контакт.\nПожалуйста, отправьте свой собственный контакт кнопкой ниже.",
    "uz": "Siz boshqa odamning kontaktini yuborgan ko'rinasiz.\n"
          "Iltimos, pastdagi tugma orqali o'zingizning kontaktingizni yuboring.",
}

_FULL_NAME_PROMPT = {
    "ru": "👤 Введите ваше настоящее ФИ.\n\n"
          "Пожалуйста, используйте реальные данные.\n"
          "Они будут отображаться врачу во время записи на приём.",
    "uz": "👤 Haqiqiy F.I.Sh.ingizni kiriting.\n\n"
          "Iltimos, haqiqiy ma'lumotlaringizdan foydalaning.\n"
          "Ular qabulga yozilishda shifokorga ko'rinadi.",
}

_BIRTH_DATE_PROMPT = {
    "ru": "Введите дату рождения в формате ДД.ММ.ГГГГ, например 05.03.1990:",
    "uz": "Tug'ilgan sanangizni KK.OO.YYYY formatida kiriting, masalan 05.03.1990:",
}

_GENDER_PROMPT = {
    "ru": "Укажите пол:",
    "uz": "Jinsingizni tanlang:",
}

_REGISTRATION_SUCCESS = {
    "ru": "Регистрация прошла успешно!",
    "uz": "Ro'yxatdan o'tish muvaffaqiyatli yakunlandi!",
}


def admin_help(lang: str) -> str:
    return _ADMIN_HELP.get(lang, _ADMIN_HELP["ru"])


def client_help(lang: str) -> str:
    return _CLIENT_HELP.get(lang, _CLIENT_HELP["ru"])


def client_help_guide(lang: str) -> str:
    return _CLIENT_HELP_GUIDE.get(lang, _CLIENT_HELP_GUIDE["ru"])


def registration_guide(lang: str) -> str:
    return _REGISTRATION_GUIDE.get(lang, _REGISTRATION_GUIDE["ru"])


def existing_user_found_prompt(full_name: str, lang: str) -> str:
    if lang == "uz":
        return (f"Siz {full_name} sifatida qayd etilgansiz\n\n"
                "Buni o'zgartirmoqchimisiz?")

    return (f"Вы были занесены как: {full_name}\n\n"
            "Хотели бы вы изменить это?")


def registration_intro(lang: str) -> str:
    return _REGISTRATION_INTRO.get(lang, _REGISTRATION_INTRO["ru"])


def send_contact_prompt(lang: str) -> str:
    return _SEND_CONTACT_PROMPT.get(lang, _SEND_CONTACT_PROMPT["ru"])


def already_registered(lang: str) -> str:
    return _ALREADY_REGISTERED.get(lang, _ALREADY_REGISTERED["ru"])


def phone_already_linked(lang: str) -> str:
    return _PHONE_ALREADY_LINKED.get(lang, _PHONE_ALREADY_LINKED["ru"])


def contact_ownership_mismatch(lang: str) -> str:
    return _CONTACT_OWNERSHIP_MISMATCH.get(lang, _CONTACT_OWNERSHIP_MISMATCH["ru"])


def full_name_prompt(lang: str) -> str:
    return _FULL_NAME_PROMPT.get(lang, _FULL_NAME_PROMPT["ru"])


def birth_date_prompt(lang: str) -> str:
    return _BIRTH_DATE_PROMPT.get(lang, _BIRTH_DATE_PROMPT["ru"])


def gender_prompt(lang: str) -> str:
    return _GENDER_PROMPT.get(lang, _GENDER_PROMPT["ru"])


def registration_success(lang: str) -> str:
    return _REGISTRATION_SUCCESS.get(lang, _REGISTRATION_SUCCESS["ru"])


def main_admin_menu_choose_option(lang: str) -> str:
    return _MAIN_ADMIN_MENU_CHOOSE_OPTION.get(lang, _MAIN_ADMIN_MENU_CHOOSE_OPTION["ru"])


def main_client_menu_choose_option(lang: str) -> str:
    return _MAIN_CLIENT_MENU_CHOOSE_OPTION.get(lang, _MAIN_CLIENT_MENU_CHOOSE_OPTION["ru"])


def admin_greeting(full_name: str, lang: str = "ru") -> str:
    if lang == "uz":
        return (f"Assalomu alaykum, {full_name}.\n\n"
                "Bu mijozlar va qabulga yozilishlarni hisobga olish uchun bot.\n\n"
                'Funksiyalar bilan tanishish uchun "Yordam" tugmasini bosing.')

    return (f"Здравствуйте, {full_name}.\n\n"
            "Это бот для учета клиентов и записей на прием.\n\n"
            'Для ознакомления с функционалом нажмите "Справка".')


def client_greeting(full_name: str, clinic_name: str, lang: str = "ru") -> str:
    if lang == "uz":
        return (f"Assalomu alaykum, {full_name}.\n\n"
                f'Bu "{clinic_name}" stomatologiyasiga qabulga yozilishlarni hisobga olish uchun bot.\n'
                f'Siz yaqinlashib kelayotgan qabullar haqida tasdiqlash yoki bekor qilish imkoniyati '
                f'bilan eslatmalar olasiz.\n\n'
                'Funksiyalar bilan tanishish uchun "Yordam" tugmasini bosing.')

    return (f"Здравствуйте, {full_name}.\n\n"
            f'Это бот для учета записей на прием в стоматологию "{clinic_name}".\n'
            f'Вы будете получать напоминания о предстоящих записях с возможностью подтвердить или отменить их.\n\n'
            'Для ознакомления с функционалом нажмите "Помощь".')
