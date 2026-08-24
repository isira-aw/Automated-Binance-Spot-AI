"""Shared test fixtures.

Unit tests never touch a live database, Redis, or Binance (§61, §63), and they
must not be influenced by a developer's local ``.env`` — so the environment is
scrubbed of trading-relevant variables before any application import, and test
settings are built with ``_env_file=None``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

_SCRUBBED = (
    "APP_ENV",
    "LOG_LEVEL",
    "TRADING_MODE",
    "LIVE_TRADING_ENABLED",
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_TESTNET",
    "CLAUDE_API_KEY",
    "CLAUDE_ENABLED",
    "OLLAMA_ENABLED",
    "OLLAMA_MODEL",
    "NEWS_ENABLED",
    "CORS_ALLOW_ORIGINS",
)
for _name in _SCRUBBED:
    os.environ.pop(_name, None)


def make_settings(**overrides: Any):
    """Build a Settings instance isolated from the ambient environment."""
    from app.config import Settings

    return Settings(_env_file=None, **overrides)


@pytest.fixture
def settings():
    return make_settings(env="testing")


@pytest.fixture
def event_bus() -> Iterator[object]:
    from app.websocket.event_bus import init_event_bus, reset_event_bus

    reset_event_bus()
    yield init_event_bus(queue_size=16)
    reset_event_bus()
