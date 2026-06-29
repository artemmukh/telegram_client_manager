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
    database_path = os.getenv("DATA_BASE")

    if not bot_token or not database_path:
        raise RuntimeError(
            "BOT_TOKEN or DB is missing. Create .env from .env.example and paste your BotFather token or DB path."
        )

    return Config(

        bot_token=bot_token,
        database_path=os.getenv("DATA_BASE"),
    )


admin_ids = list(
    map(int, os.getenv("ADMIN_IDS").split(","))
)

