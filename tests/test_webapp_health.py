"""Tests for the Mini App FastAPI app factory and health routes
(bot/webapp/server.py, bot/webapp/routes/health.py)."""

import httpx
import pytest

from bot.services.utils.auth import AuthService
from bot.webapp.server import create_webapp_app

BOT_TOKEN = "123456:TEST-BOT-TOKEN"


class FakeStaffRepository:
    async def get_staff(self, telegram_user_id):
        return None


def build_app(fake_user_repo, static_dir=None):
    return create_webapp_app(
        bot_token=BOT_TOKEN,
        user_repo=fake_user_repo,
        auth_service=AuthService(FakeStaffRepository()),
        static_dir=static_dir,
    )


def build_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://webapp",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/health", "/api/health"])
async def test_health_requires_no_auth(fake_user_repo, path):
    client = build_client(build_app(fake_user_repo))

    async with client:
        response = await client.get(path)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_static_dir_serves_index_html(fake_user_repo, tmp_path):
    (tmp_path / "index.html").write_text("<html>mini app</html>", encoding="utf-8")
    client = build_client(build_app(fake_user_repo, static_dir=tmp_path))

    async with client:
        root = await client.get("/")
        health = await client.get("/health")

    assert root.status_code == 200
    assert "mini app" in root.text
    assert health.status_code == 200


@pytest.mark.asyncio
async def test_missing_static_dir_still_serves_api(fake_user_repo, tmp_path):
    client = build_client(build_app(fake_user_repo, static_dir=tmp_path / "absent"))

    async with client:
        response = await client.get("/health")

    assert response.status_code == 200