import logging
from pathlib import Path

from aiogram import Dispatcher, Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import create_engine
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from bot.config.config import load_config
from bot.models.database import Database

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

config = load_config()

bot = Bot(token=config.bot_token)
db = Database(config.database_path)

dp = Dispatcher()

# Create data directory for job store
data_dir = Path("data")
data_dir.mkdir(exist_ok=True)

# Create sync SQLAlchemy engine for job store (separate from async bot DB).
# "zb" keeps the original, pre-existing reminders.db (its scheduled jobs
# must not be silently abandoned) -- only newer instances get their own
# distinctly-named job store file, since each now has its own main DB too.
REMINDERS_DB_NAME_BY_INSTANCE = {"zb": "reminders.db"}
reminders_db_name = REMINDERS_DB_NAME_BY_INSTANCE.get(config.instance, f"reminders_{config.instance}.db")
jobstore_db_url = f"sqlite:///{data_dir}/{reminders_db_name}"
jobstore_engine = create_engine(jobstore_db_url)

# Create scheduler with timezone support for Asia/Tashkent and persistent job store
scheduler = AsyncIOScheduler(
    timezone='Asia/Tashkent',
    jobstores={
        'default': SQLAlchemyJobStore(engine=jobstore_engine)
    },
    job_defaults={
        'misfire_grace_time': None,  # Skip missed jobs, only run future jobs
        'coalesce': True,  # Merge missed job runs
        'max_instances': 1  # Only one instance at a time
    }
)

dp["scheduler"] = scheduler
