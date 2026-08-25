"""Structured logging and secret redaction (§46)."""

from __future__ import annotations

import json
import logging

from app.core.logging_config import JsonFormatter, SecretRedactingFilter


def make_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello", args=(), exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_emits_the_required_fields():
    record = make_record(component="risk", event_type="risk_event")
    payload = json.loads(JsonFormatter().format(record))
    for field in (
        "timestamp",
        "level",
        "service",
        "component",
        "event_type",
        "request_id",
        "message",
    ):
        assert field in payload
    assert payload["component"] == "risk"


def test_optional_trading_fields_are_included_when_present():
    payload = json.loads(
        JsonFormatter().format(make_record(symbol="BTCUSDT", trade_id=7, model_version="lgbm-v1"))
    )
    assert payload["symbol"] == "BTCUSDT"
    assert payload["trade_id"] == 7
    assert payload["model_version"] == "lgbm-v1"


def test_secrets_are_redacted_before_reaching_a_handler():
    record = make_record(binance_api_secret="super-secret", api_key="abc123", symbol="BTCUSDT")
    SecretRedactingFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))
    serialised = json.dumps(payload)
    assert "super-secret" not in serialised
    assert "abc123" not in serialised
    assert payload["symbol"] == "BTCUSDT"


def test_extra_metadata_is_nested_not_flattened_over_reserved_keys():
    payload = json.loads(JsonFormatter().format(make_record(component="x", custom_field=42)))
    assert payload["metadata"]["custom_field"] == 42


def make_message_record(message: str, *, level: int = logging.ERROR) -> logging.LogRecord:
    return logging.LogRecord(
        name="test", level=level, pathname=__file__, lineno=1,
        msg=message, args=(), exc_info=None,
    )


def render(record: logging.LogRecord) -> str:
    SecretRedactingFilter().filter(record)
    return JsonFormatter().format(record)


class TestMessageTextRedaction:
    """§46: redaction must cover the message body, not just structured
    metadata keys.

    These are the paths that actually leak in practice: a driver's connection
    error embeds the whole DSN (password included) in its *message*, and that
    message is logged at ERROR -- which `WebSocketLogHandler` streams to every
    connected browser.
    """

    def test_a_database_url_password_is_redacted(self):
        output = render(
            make_message_record(
                "Database unavailable at startup: could not connect to "
                "postgresql+asyncpg://trader:SuperSecret123@postgres:5432/binance_spot_ai"
            )
        )
        assert "SuperSecret123" not in output
        # The non-secret parts stay readable, or the log is useless for debugging.
        assert "postgres:5432" in output
        assert "trader" in output

    def test_a_redis_url_password_is_redacted(self):
        output = render(make_message_record("redis://default:r3disPass@redis:6379/0 refused"))
        assert "r3disPass" not in output

    def test_an_inline_secret_assignment_is_redacted(self):
        output = render(
            make_message_record("signing failed with api_secret=abcdef123456 for request")
        )
        assert "abcdef123456" not in output

    def test_a_quoted_json_style_secret_is_redacted(self):
        output = render(make_message_record('payload {"apiKey": "KEY-THAT-LEAKED"} rejected'))
        assert "KEY-THAT-LEAKED" not in output

    def test_a_url_without_credentials_is_left_alone(self):
        output = render(make_message_record("GET https://api.binance.com/api/v3/ping failed"))
        assert "https://api.binance.com/api/v3/ping" in output

    def test_ordinary_messages_are_untouched(self):
        output = render(make_message_record("Signal generated for BTCUSDT", level=logging.INFO))
        assert "Signal generated for BTCUSDT" in output


class TestTracebackRedaction:
    def test_a_secret_in_an_exception_traceback_is_redacted(self):
        try:
            raise RuntimeError(
                "connect failed: postgresql://trader:TracebackSecret@db:5432/x"
            )
        except RuntimeError as exc:
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname=__file__, lineno=1,
                msg="Startup failed", args=(), exc_info=(type(exc), exc, exc.__traceback__),
            )
        assert "TracebackSecret" not in render(record)
