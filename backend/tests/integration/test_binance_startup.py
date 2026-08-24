"""Startup degradation for the exchange connection (§44, §106).

Binance being unreachable must stop new trades while leaving the application
running and reconnecting — it must never prevent the backend from starting.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from app.binance.errors import BinanceTransportError
from app.binance.mock import MockBinanceServer
from app.binance.rest_client import BinanceRestClient
from app.binance.service import BinanceService
from app.lifespan import _split_status, _start_binance
from app.models.enums import ComponentHealth
from tests.conftest import make_settings


def make_app() -> FastAPI:
    app = FastAPI()
    from app.websocket.event_bus import EventBus

    app.state.event_bus = EventBus(queue_size=32)
    return app


@pytest.mark.asyncio
async def test_unreachable_exchange_records_a_problem_without_raising(monkeypatch):
    app = make_app()
    settings = make_settings()
    problems: list[str] = []

    async def failing_connect(self) -> None:
        raise BinanceTransportError("network unreachable")

    monkeypatch.setattr(BinanceService, "connect", failing_connect)

    await _start_binance(app, settings, problems)

    assert len(problems) == 1
    assert "Binance unavailable at startup" in problems[0]
    # The service still exists so health reporting and reconnection work.
    assert app.state.binance is not None
    assert app.state.binance.connected is False


@pytest.mark.asyncio
async def test_failed_exchange_reports_offline_not_healthy(monkeypatch):
    app = make_app()
    problems: list[str] = []

    async def failing_connect(self) -> None:
        raise BinanceTransportError("network unreachable")

    monkeypatch.setattr(BinanceService, "connect", failing_connect)
    await _start_binance(app, make_app_settings(), problems)

    health = await app.state.binance.health()
    assert health["status"] == ComponentHealth.OFFLINE.value


def make_app_settings():
    return make_settings()


@pytest.mark.asyncio
async def test_streams_are_not_started_when_the_connection_failed(monkeypatch):
    """No stream subscription should be attempted against a dead connection."""
    app = make_app()
    problems: list[str] = []

    async def failing_connect(self) -> None:
        raise BinanceTransportError("down")

    monkeypatch.setattr(BinanceService, "connect", failing_connect)
    await _start_binance(app, make_settings(), problems)
    assert app.state.market_stream is None


@pytest.mark.asyncio
async def test_stream_failure_degrades_but_keeps_the_connection(monkeypatch):
    """A stream that cannot start is a problem, not a fatal error."""
    app = make_app()
    problems: list[str] = []
    mock = MockBinanceServer()

    async def mock_connect(self) -> None:
        self.connected = True

    async def failing_start(self, streams):
        raise OSError("stream refused")

    monkeypatch.setattr(BinanceService, "connect", mock_connect)
    from app.binance.ws_client import BinanceStreamClient

    monkeypatch.setattr(BinanceStreamClient, "start", failing_start)

    await _start_binance(app, make_settings(), problems)

    assert app.state.binance.connected is True
    assert app.state.market_stream is None
    assert any("Market data streams failed" in problem for problem in problems)
    assert mock is not None


def test_split_status_moves_extra_fields_into_metadata():
    result = _split_status(
        {"status": "ONLINE", "detail": "fine", "symbols_loaded": 3, "empty": None}
    )
    assert result["status"] is ComponentHealth.ONLINE
    assert result["detail"] == "fine"
    assert result["metadata"] == {"symbols_loaded": 3}


def test_split_status_handles_a_bare_status():
    result = _split_status({"status": "OFFLINE"})
    assert result["status"] is ComponentHealth.OFFLINE
    assert result["detail"] is None
    assert result["metadata"] == {}


@pytest.mark.asyncio
async def test_successful_startup_registers_a_live_probe():
    """After a good connect, health reflects the real service, not a placeholder."""
    settings = make_settings()
    mock = MockBinanceServer()
    client = BinanceRestClient(settings)
    client.get = mock.get  # type: ignore[method-assign]
    service = BinanceService(settings, rest_client=client)
    await service.connect()

    health = await service.health()
    assert health["status"] == ComponentHealth.ONLINE.value
    assert health["symbols_loaded"] == 3
    assert health["rate_limits_from_exchange"] is True
