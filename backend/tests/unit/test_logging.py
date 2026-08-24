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
