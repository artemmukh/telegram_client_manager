from aiogram.types import BotCommand

ADMIN_COMMANDS = [
    BotCommand(command="calendar", description="📅 Календарь записей"),
    BotCommand(command="create_client", description="➕ Создать клиента"),
    BotCommand(command="clients", description="👥 Управление клиентами"),
    BotCommand(command="create_appointment", description="📝 Создать запись"),
    BotCommand(command="appointments", description="📋 Управление записями"),
    BotCommand(command="help", description="❓ Справка по командам"),
    BotCommand(command="profile", description="👤 Мой профиль"),
]

ADMIN_COMMANDS_UZ = [
    BotCommand(command="calendar", description="📅 Yozuvlar kalendari"),
    BotCommand(command="create_client", description="➕ Mijoz qo'shish"),
    BotCommand(command="clients", description="👥 Mijozlarni boshqarish"),
    BotCommand(command="create_appointment", description="📝 Yozuv yaratish"),
    BotCommand(command="appointments", description="📋 Yozuvlarni boshqarish"),
    BotCommand(command="help", description="❓ Buyruqlar bo'yicha yordam"),
    BotCommand(command="profile", description="👤 Mening profilim"),
]

CLIENT_COMMANDS = [
    BotCommand(command="book", description="📅 Записаться на прием"),
    BotCommand(command="history", description="📖 История посещений"),
    BotCommand(command="appointments", description="📝 Мои записи"),
    BotCommand(command="help", description="❓ Как пользоваться ботом"),
    BotCommand(command="profile", description="👤 Мой профиль"),
    BotCommand(command="price", description="💰 Прайс-лист"),
    BotCommand(command="geo", description="📍 Адрес клиники"),
]

CLIENT_COMMANDS_UZ = [
    BotCommand(command="book", description="📅 Qabulga yozilish"),
    BotCommand(command="history", description="📖 Tashriflar tarixi"),
    BotCommand(command="appointments", description="📝 Mening yozuvlarim"),
    BotCommand(command="help", description="❓ Botdan qanday foydalanish"),
    BotCommand(command="profile", description="👤 Mening profilim"),
    BotCommand(command="price", description="💰 Narxlar ro'yxati"),
    BotCommand(command="geo", description="📍 Klinika manzili"),
]

DEFAULT_COMMANDS = [
    BotCommand(command="start", description="🚀 Запустить бота"),
]

_ADMIN_COMMANDS_BY_LANG = {"ru": ADMIN_COMMANDS, "uz": ADMIN_COMMANDS_UZ}
_CLIENT_COMMANDS_BY_LANG = {"ru": CLIENT_COMMANDS, "uz": CLIENT_COMMANDS_UZ}


def admin_commands(lang: str = "ru") -> list[BotCommand]:
    return _ADMIN_COMMANDS_BY_LANG.get(lang, ADMIN_COMMANDS)


def client_commands(lang: str = "ru") -> list[BotCommand]:
    return _CLIENT_COMMANDS_BY_LANG.get(lang, CLIENT_COMMANDS)
