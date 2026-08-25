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

_SECRET_KEY = r"(?:api[_-]?key|api[_-]?secret|secret|token|password|passwd|pwd)"

# Value-level patterns, applied to free text (log messages and tracebacks).
# Keys alone are not enough: the leaks that actually happen in practice come
# from a driver embedding a whole DSN in its own error message.
_VALUE_PATTERNS = (
    # scheme://user:PASSWORD@host -- keeps the scheme, user and host visible,
    # since a connection error is useless for debugging without them.
    re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s:/@]+:)([^\s@]+)(@)"),
    # key=VALUE / key: VALUE, optionally quoted, as in a signed request dump.
    re.compile(rf"(?i)([\"']?{_SECRET_KEY}[\"']?\s*[=:]\s*)([\"']?)([^\s,;&\"'}}\)]+)\2"),
)


def redact_text(text: str, replacement: str = "***REDACTED***") -> str:
    """Strip credential values out of free text.

    Deliberately conservative about what it removes: a URL with no
    credentials, and a message with no secret-looking assignment, come
    through untouched. An over-eager redactor produces logs nobody can debug
    with, which is its own kind of failure.
    """
    text = _VALUE_PATTERNS[0].sub(rf"\1{replacement}\3", text)
    return _VALUE_PATTERNS[1].sub(rf"\1\2{replacement}\2", text)


class SecretRedactingFilter(logging.Filter):
    """Redact secrets from structured metadata, message text, and tracebacks.

    Three separate paths, because a secret only has to escape through one:

    1. ``extra=`` metadata whose *key* looks secret (e.g. ``api_secret=...``).
    2. The message body, where a driver's own error text carries a full DSN.
    3. The formatted exception, for the same reason one level deeper.

    (2) and (3) matter most: those records are logged at ERROR, and
    :class:`~app.monitoring.log_stream.WebSocketLogHandler` streams ERROR to
    every connected browser (§46, §60).
    """

    REDACTED = "***REDACTED***"

    def filter(self, record: logging.LogRecord) -> bool:
        for key in list(record.__dict__):
            if key in _RESERVED:
                continue
            if any(pattern.search(key) for pattern in _SECRET_PATTERNS):
                record.__dict__[key] = self.REDACTED

        # Resolve args into the message now, then scrub: redacting the
        # template alone would miss a secret passed as a %s argument.
        message = record.getMessage()
        cleaned = redact_text(message, self.REDACTED)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()

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
            # Scrubbed here rather than in the filter: the traceback is only
            # rendered to text at format time, and it routinely carries the
            # same DSN the message does (§46).
            payload["exception"] = redact_text(self.formatException(record.exc_info))

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
