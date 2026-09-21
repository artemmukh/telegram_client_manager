"""Telegram Mini App initData validation and FastAPI auth dependency."""

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request, status

from bot.models.user import User
from bot.repositories.user_repository import UserRepository
from bot.services.utils.auth import AuthService
from bot.utils.role import Role

logger = logging.getLogger(__name__)

_AUTH_SCHEME = "tma"
_MAX_INIT_DATA_LEN = 8192


def validate_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = 86400,
) -> dict | None:
    """Validate Telegram WebApp initData per the official spec.

    Returns the parsed key-value pairs (including the raw ``user`` JSON
    string) on success, or ``None`` on any validation failure.
    """
    if not init_data or not bot_token or len(init_data) > _MAX_INIT_DATA_LEN:
        return None

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True)
    except ValueError:
        return None

    if not pairs:
        return None

    received_hash = None
    data_pairs = []
    for key, value in pairs:
        if key == "hash":
            received_hash = value
        else:
            data_pairs.append((key, value))

    if not received_hash:
        return None

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(data_pairs)
    )

    secret = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        secret, data_check_string.encode(), hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    auth_date_raw = dict(data_pairs).get("auth_date")
    if auth_date_raw is None:
        return None
    try:
        auth_date = int(auth_date_raw)
    except ValueError:
        return None
    if time.time() - auth_date > max_age_seconds:
        return None

    return dict(data_pairs)


@dataclass(frozen=True)
class WebappPrincipal:
    """Authenticated Mini App user."""

    user: User
    role: Role


async def get_current_user(request: Request) -> WebappPrincipal:
    """Resolve the Telegram user from the ``Authorization: tma <initData>`` header."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
    )

    authorization = request.headers.get("Authorization", "")
    scheme, _, init_data = authorization.partition(" ")
    if scheme.lower() != _AUTH_SCHEME or not init_data.strip():
        raise unauthorized

    user_repo: UserRepository = request.app.state.user_repo
    auth_service: AuthService = request.app.state.auth_service

    parsed = validate_init_data(init_data.strip(), request.app.state.bot_token)
    if parsed is None:
        raise unauthorized

    user_json = parsed.get("user")
    if not user_json:
        raise unauthorized
    try:
        telegram_user = json.loads(user_json)
        telegram_user_id = int(telegram_user["id"])
    except (ValueError, TypeError, KeyError):
        logger.warning("Mini App initData contained malformed user payload")
        raise unauthorized from None

    user = await user_repo.get_user_by_telegram_id(telegram_user_id)
    if user is None:
        raise unauthorized

    role = await auth_service.resolve_current_role(user)
    return WebappPrincipal(user=user, role=role)
