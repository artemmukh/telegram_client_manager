import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    database_path: str
    instance: str


def load_config() -> Config:
    load_dotenv()

    instance = os.getenv("BOT_INSTANCE")
    database_path = os.getenv("DATA_BASE")

    token_by_instance = {
        "zb": os.getenv("BOT_TOKEN_ZB"),
        "mm": os.getenv("BOT_TOKEN_MM"),
    }

    if instance not in token_by_instance:
        raise RuntimeError(
            "BOT_INSTANCE is missing or invalid. Set BOT_INSTANCE=zb or BOT_INSTANCE=mm in your environment."
        )

    bot_token = token_by_instance[instance]

    if not bot_token or not database_path:
        raise RuntimeError(
            "BOT_TOKEN or DB is missing. Create .env from .env.example and paste your BotFather token or DB path."
        )

    return Config(
        bot_token=bot_token,
        database_path=database_path,
        instance=instance,
    )




