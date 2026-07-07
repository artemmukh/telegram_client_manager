import logging
from pathlib import Path

from aiogram import Dispatcher, Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import create_engine
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from bot.config.config import load_config
from bot.models.database import Database

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

bot = Bot(token=load_config().bot_token)
db = Database(load_config().database_path)

dp = Dispatcher()

# Create data directory for job store
data_dir = Path("data")
data_dir.mkdir(exist_ok=True)

# Create sync SQLAlchemy engine for job store (separate from async bot DB)
jobstore_db_url = f"sqlite:///{data_dir}/reminders.db"
jobstore_engine = create_engine(jobstore_db_url)

# Create job store tables
from sqlalchemy.orm import declarative_base
Base = declarative_base()
Base.metadata.create_all(jobstore_engine)

# Create scheduler with timezone support for Asia/Tashkent and persistent job store
scheduler = AsyncIOScheduler(
    timezone='Asia/Tashkent',
    jobstores={
        'default': SQLAlchemyJobStore(engine=jobstore_engine)
    },
    job_defaults={
        'misfire_grace_time': 0,  # Skip missed jobs, only run future jobs
        'coalesce': True,  # Merge missed job runs
        'max_instances': 1  # Only one instance at a time
    }
)

dp["scheduler"] = scheduler
