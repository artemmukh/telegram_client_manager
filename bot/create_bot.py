import logging

from aiogram import Dispatcher, Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config.config import load_config

bot = Bot(token=load_config().bot_token)
db = load_config().database_path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone='Asia/Tashkent')
