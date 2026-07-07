import logging

from aiogram import Dispatcher, Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config.config import load_config
from bot.models.database import Database

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

bot = Bot(token=load_config().bot_token)
db = Database(load_config().database_path)

dp = Dispatcher()

# Create scheduler with timezone support for Asia/Tashkent
scheduler = AsyncIOScheduler(timezone='Asia/Tashkent')
dp["scheduler"] = scheduler
