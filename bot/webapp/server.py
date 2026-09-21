"""FastAPI application factory for the Telegram Mini App backend."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from bot.repositories.user_repository import UserRepository
from bot.services.utils.auth import AuthService
from bot.webapp.routes.health import router as health_router

logger = logging.getLogger(__name__)


def create_webapp_app(
    *,
    bot_token: str,
    user_repo: UserRepository,
    auth_service: AuthService,
    static_dir: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Medical Appointment Mini App")
    app.state.bot_token = bot_token
    app.state.user_repo = user_repo
    app.state.auth_service = auth_service

    app.include_router(health_router)

    if static_dir is not None and static_dir.is_dir():
        app.mount(
            "/", StaticFiles(directory=static_dir, html=True), name="webapp",
        )
    else:
        logger.info(
            "Static dir %s not found; serving API routes only", static_dir,
        )

    return app
