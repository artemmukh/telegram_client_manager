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

CLIENT_COMMANDS = [
    BotCommand(command="book", description="📅 Записаться на прием"),
    BotCommand(command="history", description="📖 История посещений"),
    BotCommand(command="appointments", description="📝 Мои записи"),
    BotCommand(command="help", description="❓ Как пользоваться ботом"),
    BotCommand(command="profile", description="👤 Мой профиль"),
    BotCommand(command="price", description="💰 Прайс-лист"),
    BotCommand(command="location", description="📍 Адрес клиники"),
]