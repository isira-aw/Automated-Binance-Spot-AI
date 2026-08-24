"""BinanceService lifecycle and health semantics (§43, §44, §70)."""

from __future__ import annotations

import pytest

from app.binance.errors import BinanceTransportError
from app.binance.mock import MockBinanceServer
from app.binance.rest_client import BinanceRestClient
from app.binance.service import BinanceService
from app.core.time_utils import utc_now
from app.models.enums import ComponentHealth
from tests.conftest import make_settings


def build_service(**setting_overrides) -> tuple[BinanceService, MockBinanceServer]:
    settings = make_settings(**setting_overrides)
    mock = MockBinanceServer()
    client = BinanceRestClient(settings)
    client.get = mock.get  # type: ignore[method-assign]
    return BinanceService(settings, rest_client=client), mock


@pytest.mark.asyncio
async def test_connect_syncs_clock_and_loads_metadata():
    service, _ = build_service()
    await service.connect()
    assert service.connected is True
    assert service.rest.time_sync.synchronised is True
    assert service.metadata.is_loaded is True
    assert service.symbol("BTCUSDT").tradable is True


@pytest.mark.asyncio
async def test_connect_adopts_exchange_rate_limits():
    service, _ = build_service()
    await service.connect()
    assert service.rest.rate_limiter.configured_from_exchange is True


@pytest.mark.asyncio
async def test_health_is_offline_before_connecting():
    service, _ = build_service()
    assert (await service.health())["status"] == ComponentHealth.OFFLINE.value


@pytest.mark.asyncio
async def test_health_is_online_after_connecting():
    service, _ = build_service()
    await service.connect()
    health = await service.health()
    assert health["status"] == ComponentHealth.ONLINE.value
    assert health["rate_limits_from_exchange"] is True
    assert health["symbols_loaded"] == 3


@pytest.mark.asyncio
async def test_health_degrades_after_a_failure_but_before_the_threshold():
    service, _ = build_service()
    await service.connect()
    service.rest.consecutive_failures = 1
    assert (await service.health())["status"] == ComponentHealth.DEGRADED.value


@pytest.mark.asyncio
async def test_health_errors_once_the_failure_threshold_is_reached():
    """Feeds api_failure_protection: repeated failures must stop trading (§31)."""
    service, _ = build_service()
    await service.connect()
    threshold = service._settings.risk.api_failure_protection_threshold
    service.rest.consecutive_failures = threshold
    health = await service.health()
    assert health["status"] == ComponentHealth.ERROR.value
    assert health["consecutive_failures"] == threshold


@pytest.mark.asyncio
async def test_connect_failure_surfaces_and_leaves_service_disconnected():
    service, mock = build_service()
    mock.fail_next = BinanceTransportError("network down")
    with pytest.raises(BinanceTransportError):
        await service.connect()
    assert service.connected is False
    assert (await service.health())["status"] == ComponentHealth.OFFLINE.value


@pytest.mark.asyncio
async def test_stream_with_no_data_is_stale():
    """Absence of data is never evidence of fresh data (§44)."""
    service, _ = build_service()
    assert service.data_is_stale() is True


@pytest.mark.asyncio
async def test_fresh_stream_data_is_not_stale():
    service, _ = build_service()
    service.stream.state.last_message_at = utc_now().isoformat()
    assert service.data_is_stale() is False


@pytest.mark.asyncio
async def test_old_stream_data_is_stale():
    from datetime import timedelta

    service, _ = build_service()
    age = service._settings.risk.stale_data_protection_seconds + 60
    service.stream.state.last_message_at = (utc_now() - timedelta(seconds=age)).isoformat()
    assert service.data_is_stale() is True


@pytest.mark.asyncio
async def test_market_data_health_reports_offline_without_subscriptions():
    service, _ = build_service()
    assert (await service.market_data_health())["status"] == ComponentHealth.OFFLINE.value


@pytest.mark.asyncio
async def test_market_data_health_errors_when_disconnected():
    service, _ = build_service()
    service.stream.state.subscribed = ("btcusdt@kline_4h",)
    service.stream.state.connected = False
    assert (await service.market_data_health())["status"] == ComponentHealth.ERROR.value


@pytest.mark.asyncio
async def test_market_data_health_degrades_on_stale_data():
    """Connected but stale must not read as healthy — trading is blocked."""
    from datetime import timedelta

    service, _ = build_service()
    service.stream.state.subscribed = ("btcusdt@kline_4h",)
    service.stream.state.connected = True
    age = service._settings.risk.stale_data_protection_seconds + 60
    service.stream.state.last_message_at = (utc_now() - timedelta(seconds=age)).isoformat()
    health = await service.market_data_health()
    assert health["status"] == ComponentHealth.DEGRADED.value
    assert "stale" in health["detail"].lower()


@pytest.mark.asyncio
async def test_market_data_health_online_when_connected_and_fresh():
    service, _ = build_service()
    service.stream.state.subscribed = ("btcusdt@kline_4h",)
    service.stream.state.connected = True
    service.stream.state.last_message_at = utc_now().isoformat()
    assert (await service.market_data_health())["status"] == ComponentHealth.ONLINE.value


def test_service_exposes_no_order_or_withdrawal_surface():
    """Phase 5 is read-only, and withdrawals never exist anywhere (§70)."""
    forbidden = ("withdraw", "order", "cancel", "transfer")
    names = [name for name in dir(BinanceService) if not name.startswith("_")]
    assert [name for name in names if any(word in name.lower() for word in forbidden)] == []


def test_no_withdrawal_endpoint_anywhere_in_the_package():
    from pathlib import Path

    package = Path(__file__).resolve().parents[2] / "app" / "binance"
    for module in package.glob("*.py"):
        assert "sapi/v1/capital/withdraw" not in module.read_text()
