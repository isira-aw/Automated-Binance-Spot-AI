"""Structured JSON logging (§46) with rotation (§104).

Log records never contain secrets: :class:`SecretRedactingFilter` scrubs values
that look like API keys before a record reaches any handler.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|api[_-]?secret|secret|token|password)"),
)


class SecretRedactingFilter(logging.Filter):
    """Redact obviously-secret values from messages and structured metadata."""

    REDACTED = "***REDACTED***"

    def filter(self, record: logging.LogRecord) -> bool:
        for key in list(record.__dict__):
            if key in _RESERVED:
                continue
            if any(pattern.search(key) for pattern in _SECRET_PATTERNS):
                record.__dict__[key] = self.REDACTED
        return True


class JsonFormatter(logging.Formatter):
    """Render a log record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=UTC
            ).isoformat(),
            "level": record.levelname,
            "service": getattr(record, "service", "backend"),
            "component": getattr(record, "component", record.name),
            "event_type": getattr(record, "event_type", "log"),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
            "message": record.getMessage(),
        }
        for optional in ("symbol", "trade_id", "model_version", "strategy_version"):
            value = getattr(record, optional, None)
            if value is not None:
                payload[optional] = value

        metadata = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED and key not in payload
        }
        if metadata:
            payload["metadata"] = metadata

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(
    level: str = "INFO",
    *,
    log_dir: Path | None = None,
    service: str = "backend",
    max_bytes: int = 20 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Install the JSON formatter on stdout and (optionally) a rotating file."""

    formatter = JsonFormatter()
    redactor = SecretRedactingFilter()

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    stream.addFilter(redactor)
    root.addHandler(stream)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(
            log_dir / f"{service}.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        rotating.setFormatter(formatter)
        rotating.addFilter(redactor)
        root.addHandler(rotating)

    # uvicorn installs its own handlers; route them through ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True


def get_logger(component: str) -> logging.LoggerAdapter[logging.Logger]:
    """Return a logger that always tags records with ``component``."""

    return logging.LoggerAdapter(logging.getLogger(component), {"component": component})
