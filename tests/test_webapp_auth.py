"""Tests for the Mini App initData authentication layer
(bot/webapp/auth.py): signature validation, auth_date freshness, and the
FastAPI dependency that resolves the current user and role."""

import hashlib
import hmac
import json
import time
from typing import Annotated
from urllib.parse import urlencode

import httpx
import pytest
from fastapi import Depends

from bot.models.staff import Staff
from bot.models.user import User
from bot.services.utils.auth import AuthService
from bot.utils.role import Role
from bot.webapp.auth import WebappPrincipal, get_current_user, validate_init_data
from bot.webapp.server import create_webapp_app

BOT_TOKEN = "123456:TEST-BOT-TOKEN"
TELEGRAM_ID = 555001
CLINIC_ID = 1
OTHER_CLINIC_ID = 2


class FakeStaffRepository:
    """Minimal drop-in for StaffRepository.get_staff(), which AuthService uses."""

    def __init__(self, staff: Staff | None = None):
        self.staff = staff

    async def get_staff(self, telegram_user_id):
        if self.staff is not None and self.staff.telegram_user_id == telegram_user_id:
            return self.staff
        return None


def build_init_data(
    user_id: int = TELEGRAM_ID,
    auth_date: int | None = None,
    hash_override: str | None = None,
    user_payload: str | None = None,
    include_auth_date: bool = True,
    bot_token: str = BOT_TOKEN,
) -> str:
    pairs = {
        "query_id": "AAHdF6IQAAAAAN0Xo",
        "user": user_payload if user_payload is not None else json.dumps(
            {"id": user_id, "first_name": "Test", "language_code": "ru"},
            separators=(",", ":"),
        ),
    }
    if include_auth_date:
        pairs["auth_date"] = str(auth_date if auth_date is not None else int(time.time()))

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()

    pairs["hash"] = hash_override if hash_override is not None else digest
    return urlencode(pairs)


def build_client(user_repo, auth_service, bot_token: str = BOT_TOKEN) -> httpx.AsyncClient:
    app = create_webapp_app(
        bot_token=bot_token, user_repo=user_repo, auth_service=auth_service,
    )

    @app.get("/api/me")
    async def me(principal: Annotated[WebappPrincipal, Depends(get_current_user)]) -> dict:
        return {
            "telegram_user_id": principal.user.telegram_user_id,
            "clinic_id": principal.user.clinic_id,
            "role": principal.role.value,
        }

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://webapp",
    )


def build_client_and_service(fake_user_repo, staff: Staff | None = None):
    auth_service = AuthService(FakeStaffRepository(staff))
    return build_client(fake_user_repo, auth_service), auth_service


def client_user(telegram_user_id: int = TELEGRAM_ID, clinic_id: int = CLINIC_ID) -> User:
    return User(
        full_name="Client User",
        phone="+998900000001",
        role=Role.CLIENT,
        telegram_user_id=telegram_user_id,
        ID=10,
        clinic_id=clinic_id,
    )


# --- validate_init_data -----------------------------------------------------

def test_validate_init_data_accepts_valid_payload():
    parsed = validate_init_data(build_init_data(), BOT_TOKEN)

    assert parsed is not None
    assert json.loads(parsed["user"])["id"] == TELEGRAM_ID
    assert "hash" not in parsed


def test_validate_init_data_rejects_tampered_hash():
    assert validate_init_data(build_init_data(hash_override="0" * 64), BOT_TOKEN) is None


def test_validate_init_data_rejects_other_bot_token():
    init_data = build_init_data()

    assert validate_init_data(init_data, "another:token") is None


def test_validate_init_data_rejects_expired_auth_date():
    stale = build_init_data(auth_date=int(time.time()) - 86401)

    assert validate_init_data(stale, BOT_TOKEN) is None


def test_validate_init_data_rejects_missing_auth_date():
    assert validate_init_data(build_init_data(include_auth_date=False), BOT_TOKEN) is None


def test_validate_init_data_rejects_missing_hash():
    assert validate_init_data("auth_date=1&user=%7B%7D", BOT_TOKEN) is None


@pytest.mark.parametrize("init_data", ["", "not-a-query-string", "a=b" * 5000])
def test_validate_init_data_rejects_malformed_input(init_data):
    assert validate_init_data(init_data, BOT_TOKEN) is None


# --- get_current_user dependency -------------------------------------------

@pytest.mark.asyncio
async def test_authorized_request_returns_client_role(fake_user_repo):
    fake_user_repo.users_by_id[10] = client_user()
    client, _ = build_client_and_service(fake_user_repo)

    async with client:
        response = await client.get(
            "/api/me", headers={"Authorization": f"tma {build_init_data()}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "telegram_user_id": TELEGRAM_ID,
        "clinic_id": CLINIC_ID,
        "role": "client",
    }


@pytest.mark.asyncio
async def test_staff_of_same_clinic_gets_admin_role(fake_user_repo):
    fake_user_repo.users_by_id[10] = client_user()
    staff = Staff(telegram_user_id=TELEGRAM_ID, clinic_id=CLINIC_ID)
    client, _ = build_client_and_service(fake_user_repo, staff)

    async with client:
        response = await client.get(
            "/api/me", headers={"Authorization": f"tma {build_init_data()}"},
        )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_staff_of_other_clinic_stays_client(fake_user_repo):
    fake_user_repo.users_by_id[10] = client_user()
    staff = Staff(telegram_user_id=TELEGRAM_ID, clinic_id=OTHER_CLINIC_ID)
    client, _ = build_client_and_service(fake_user_repo, staff)

    async with client:
        response = await client.get(
            "/api/me", headers={"Authorization": f"tma {build_init_data()}"},
        )

    assert response.status_code == 200
    assert response.json()["role"] == "client"


@pytest.mark.asyncio
async def test_rejects_tampered_hash(fake_user_repo):
    fake_user_repo.users_by_id[10] = client_user()
    client, _ = build_client_and_service(fake_user_repo)
    init_data = build_init_data(hash_override="f" * 64)

    async with client:
        response = await client.get(
            "/api/me", headers={"Authorization": f"tma {init_data}"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.asyncio
async def test_rejects_expired_auth_date(fake_user_repo):
    fake_user_repo.users_by_id[10] = client_user()
    client, _ = build_client_and_service(fake_user_repo)
    init_data = build_init_data(auth_date=int(time.time()) - 86401)

    async with client:
        response = await client.get(
            "/api/me", headers={"Authorization": f"tma {init_data}"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rejects_unknown_telegram_id(fake_user_repo):
    client, _ = build_client_and_service(fake_user_repo)

    async with client:
        response = await client.get(
            "/api/me", headers={"Authorization": f"tma {build_init_data()}"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rejects_malformed_user_payload(fake_user_repo):
    fake_user_repo.users_by_id[10] = client_user()
    client, _ = build_client_and_service(fake_user_repo)
    init_data = build_init_data(user_payload="not-json")

    async with client:
        response = await client.get(
            "/api/me", headers={"Authorization": f"tma {init_data}"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rejects_user_payload_without_id(fake_user_repo):
    fake_user_repo.users_by_id[10] = client_user()
    client, _ = build_client_and_service(fake_user_repo)
    init_data = build_init_data(user_payload=json.dumps({"first_name": "Test"}))

    async with client:
        response = await client.get(
            "/api/me", headers={"Authorization": f"tma {init_data}"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authorization",
    [None, "", "tma", "tma   ", "Bearer some-token", "tma-not-separated"],
)
async def test_rejects_missing_or_wrong_authorization_header(fake_user_repo, authorization):
    fake_user_repo.users_by_id[10] = client_user()
    client, _ = build_client_and_service(fake_user_repo)
    headers = {} if authorization is None else {"Authorization": authorization}

    async with client:
        response = await client.get("/api/me", headers=headers)

    assert response.status_code == 401