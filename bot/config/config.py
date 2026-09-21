import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    database_path: str
    instance: str
    ollama_base_url: str
    ollama_model: str
    mistral_api_key: str | None
    mistral_model: str
    webapp_host: str
    webapp_port: int
    webapp_base_url: str | None
    openrouter_api_key: str | None
    openrouter_model: str


def load_config() -> Config:
    load_dotenv()

    instance = os.getenv("BOT_INSTANCE")
    database_path = os.getenv("DATA_BASE")
    ollama_base_url = os.getenv("OLLAMA_BASE_URL")
    ollama_model = os.getenv("OLLAMA_MODEL")
    mistral_api_key = os.getenv("MISTRAL_API_KEY")
    mistral_model = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

    webapp_host = os.getenv("WEBAPP_HOST", "0.0.0.0")
    webapp_port = int(os.getenv("WEBAPP_PORT", "8080"))
    webapp_base_url = os.getenv("WEBAPP_BASE_URL")
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    openrouter_model = os.getenv("OPENROUTER_MODEL", "openrouter/auto")

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
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        mistral_api_key=mistral_api_key,
        mistral_model=mistral_model,
        webapp_host=webapp_host,
        webapp_port=webapp_port,
        webapp_base_url=webapp_base_url,
        openrouter_api_key=openrouter_api_key,
        openrouter_model=openrouter_model,
    )




