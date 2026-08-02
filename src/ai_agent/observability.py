"""Safe, structured server-side diagnostics for Finance Agent.

The application handles private research requests and service credentials, so
diagnostic events deliberately contain only operational metadata.  In
particular, request content, prompts, tool arguments/results, headers, and
exception messages are never written to this logger.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from os import getenv
from pathlib import Path
from time import monotonic
from uuid import uuid4

LOGGER_NAME = "finance_agent"
_LOGGER = logging.getLogger(LOGGER_NAME)
_LOGGER.addHandler(logging.NullHandler())
_LOGGER.propagate = False
_REQUEST_ID: ContextVar[str | None] = ContextVar("finance_agent_request_id", default=None)
_SENSITIVE_FIELD_MARKERS = (
    "argument",
    "authorization",
    "content",
    "credential",
    "header",
    "key",
    "message",
    "prompt",
    "request_body",
    "response",
    "result",
    "secret",
    "token",
)


def get_logger() -> logging.Logger:
    """Return the dedicated application logger without configuring handlers."""

    return _LOGGER


def new_request_id() -> str:
    """Generate an opaque correlation ID safe to expose in an HTTP header."""

    return uuid4().hex


def bind_request_id(request_id: str) -> Token[str | None]:
    """Associate subsequent events with one HTTP request."""

    return _REQUEST_ID.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the request context after an HTTP request finishes."""

    _REQUEST_ID.reset(token)


def log_event(event: str, *, level: int = logging.INFO, **fields: object) -> None:
    """Emit one JSON-ready operational event without sensitive payload data."""

    if not event or not event.replace("_", "").isalnum():
        raise ValueError("event must contain only letters, numbers, and underscores")
    safe_fields = _safe_fields(fields)
    request_id = _REQUEST_ID.get()
    if request_id:
        safe_fields["request_id"] = request_id
    get_logger().log(level, event, extra={"event_name": event, "event_fields": safe_fields})


def elapsed_milliseconds(started_at: float) -> int:
    """Return a non-negative monotonic duration suitable for diagnostic logs."""

    return max(0, round((monotonic() - started_at) * 1_000))


def configure_server_logging() -> Path | None:
    """Configure JSON Lines console and rotating-file logs for the API server.

    ``AGENT_LOG_DIR`` may override the default current-user log directory and
    ``AGENT_LOG_LEVEL`` controls this logger independently of Uvicorn's own
    ``AGENT_API_LOG_LEVEL``.  A file-handler failure must never prevent the
    local API from starting, so console logging remains available in that case.
    """

    logger = get_logger()
    logger.setLevel(_log_level())
    logger.propagate = False
    if any(getattr(handler, "_finance_agent_handler", False) for handler in logger.handlers):
        return _configured_log_path(logger)

    formatter = _JsonLineFormatter()
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console._finance_agent_handler = True  # type: ignore[attr-defined]
    logger.addHandler(console)

    log_path = _log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        log_event("log_file_unavailable", level=logging.WARNING)
        return None
    file_handler.setFormatter(formatter)
    file_handler._finance_agent_handler = True  # type: ignore[attr-defined]
    file_handler._finance_agent_log_path = log_path  # type: ignore[attr-defined]
    logger.addHandler(file_handler)
    log_event("server_logging_configured", log_path=str(log_path))
    return log_path


class _JsonLineFormatter(logging.Formatter):
    """Render only event metadata as one machine-readable UTF-8 line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event_name", record.getMessage()),
        }
        fields = getattr(record, "event_fields", {})
        if isinstance(fields, dict):
            payload.update(fields)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _safe_fields(fields: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for name, value in fields.items():
        normalized_name = name.casefold()
        if any(marker in normalized_name for marker in _SENSITIVE_FIELD_MARKERS):
            continue
        if isinstance(value, (bool, int, float)) or value is None:
            safe[name] = value
        elif isinstance(value, str):
            safe[name] = value[:160]
        elif isinstance(value, (tuple, list)) and all(isinstance(item, (bool, int, float, str)) for item in value):
            safe[name] = [item[:160] if isinstance(item, str) else item for item in value][:20]
        else:
            safe[name] = type(value).__name__
    return safe


def _log_path() -> Path:
    configured_directory = getenv("AGENT_LOG_DIR", "").strip()
    if configured_directory:
        return Path(configured_directory) / "finance-agent.jsonl"
    local_application_data = getenv("LOCALAPPDATA", "").strip()
    base_directory = Path(local_application_data) if local_application_data else Path.home() / "AppData" / "Local"
    return base_directory / "FinanceAgent" / "logs" / "finance-agent.jsonl"


def _configured_log_path(logger: logging.Logger) -> Path | None:
    for handler in logger.handlers:
        path = getattr(handler, "_finance_agent_log_path", None)
        if isinstance(path, Path):
            return path
    return None


def _log_level() -> int:
    value = getenv("AGENT_LOG_LEVEL", "INFO").strip().upper()
    return getattr(logging, value, logging.INFO) if value in {"DEBUG", "INFO", "WARNING", "ERROR"} else logging.INFO
