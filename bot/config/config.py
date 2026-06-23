import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    database_path: str

def load_config() -> Config:
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError(
            "BOT_TOKEN is missing. Create .env from .env.example and paste your BotFather token."
        )

    return Config(

        bot_token=bot_token,
        database_path=os.getenv("DATABASE")

    )
