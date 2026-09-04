import logging
import re
import uuid
from contextvars import ContextVar, Token
from typing import Any

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_SAFE_FIELD_NAMES = frozenset(
    {
        "appointment_id",
        "attempted_count",
        "broadcast_id",
        "clinic_id",
        "delivered_count",
        "duration_ms",
        "error_function",
        "error_line",
        "error_type",
        "failed_count",
        "job_type",
        "outcome",
        "reason_code",
        "recipient_count",
        "skipped_count",
        "staff_id",
        "status",
        "update_kind",
    }
)
_LOGFMT_UNSAFE_CHARS = re.compile(r"[\s=\"\\]")


def bind_request_context(request_id: str | None = None) -> Token[str | None]:
    return _request_id.set(request_id or uuid.uuid4().hex[:12])


def reset_request_context(token: Token[str | None]) -> None:
    _request_id.reset(token)


def get_request_id() -> str | None:
    return _request_id.get()


def log_event(logger: logging.Logger, level: int, event: str, *, exc_info: bool = False, **fields: Any) -> None:
    parts = [f"event={_format_value(event)}"]
    request_id = get_request_id()
    if request_id is not None:
        parts.append(f"request_id={_format_value(request_id)}")

    for name in sorted(_SAFE_FIELD_NAMES.intersection(fields)):
        parts.append(f"{name}={_format_value(fields[name])}")

    logger.log(level, " ".join(parts), exc_info=exc_info)


def _format_value(value: object) -> str:
    text = str(value)
    if _LOGFMT_UNSAFE_CHARS.search(text):
        escaped = (
            text.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\r", "\\r")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    return text
