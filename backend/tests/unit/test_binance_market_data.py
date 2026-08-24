"""Market data parsing, with the candle-closure rule that guards §16 and §18.

Using an open candle as a feature input leaks information the model would not
have had at decision time, so closure is enforced here rather than left to
callers.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import pairwise

import pytest

from app.binance.errors import BinanceRequestError
from app.binance.market_data import MarketDataService
from app.binance.mock import MockBinanceServer
from app.binance.rest_client import BinanceRestClient
from app.core.time_utils import timeframe_seconds, utc_now
from tests.conftest import make_settings


@pytest.fixture
def service() -> tuple[MarketDataService, MockBinanceServer]:
    settings = make_settings()
    mock = MockBinanceServer()
    client = BinanceRestClient(settings)
    client.get = mock.get  # type: ignore[method-assign]
    # Sync against the mock's clock the way a real handshake would: the local
    # clock is the host's, so the offset carries the whole difference.  This
    # also means is_closed is evaluated against exchange time, not wall clock.
    local_now_ms = int(utc_now().timestamp() * 1000)
    client.time_sync.observe(
        sent_ms=local_now_ms,
        server_ms=mock.server_time_ms,
        received_ms=local_now_ms,
    )
    return MarketDataService(client, settings), mock


@pytest.mark.asyncio
async def test_klines_parse_into_ohlcv(service):
    market, _ = service
    klines = await market.klines("BTCUSDT", "1h", limit=5)
    assert len(klines) == 5
    first = klines[0]
    assert first.symbol == "BTCUSDT"
    assert first.timeframe == "1h"
    assert first.high >= first.open and first.high >= first.close
    assert first.low <= first.open and first.low <= first.close
    assert isinstance(first.close, Decimal)


@pytest.mark.asyncio
async def test_open_times_are_utc_and_evenly_spaced(service):
    market, _ = service
    klines = await market.klines("BTCUSDT", "4h", limit=6)
    step = timeframe_seconds("4h")
    for earlier, later in pairwise(klines):
        assert earlier.open_time.tzinfo is not None
        assert (later.open_time - earlier.open_time).total_seconds() == step


@pytest.mark.asyncio
async def test_close_time_is_the_exclusive_boundary(service):
    """Binance's close_time is the last millisecond inside the candle; the
    system stores the exclusive boundary so close == next open."""
    market, _ = service
    klines = await market.klines("BTCUSDT", "1h", limit=3)
    for earlier, later in pairwise(klines):
        assert earlier.close_time == later.open_time


@pytest.mark.asyncio
async def test_the_most_recent_candle_is_open(service):
    """The live API's last row is the in-progress candle."""
    market, _ = service
    klines = await market.klines("BTCUSDT", "1h", limit=10)
    assert klines[-1].is_closed is False
    assert all(kline.is_closed for kline in klines[:-1])


@pytest.mark.asyncio
async def test_closed_klines_exclude_the_open_candle(service):
    """This is the §18 guard: an open candle must never reach feature building."""
    market, _ = service
    everything = await market.klines("BTCUSDT", "1h", limit=10)
    closed = await market.closed_klines("BTCUSDT", "1h", limit=10)
    assert len(closed) == len(everything) - 1
    assert all(kline.is_closed for kline in closed)
    assert everything[-1].open_time not in {kline.open_time for kline in closed}


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, 1001])
async def test_invalid_limits_are_rejected_locally(service, limit):
    """Rejected before the request, so a typo cannot burn rate-limit weight."""
    market, mock = service
    with pytest.raises(BinanceRequestError):
        await market.klines("BTCUSDT", "1h", limit=limit)
    assert mock.request_log == []


@pytest.mark.asyncio
async def test_exchange_info_updates_the_rate_limiter(service):
    """Live limits replace the conservative fallbacks (§71)."""
    market, _ = service
    assert market._client.rate_limiter.configured_from_exchange is False
    await market.exchange_info(["BTCUSDT"])
    assert market._client.rate_limiter.configured_from_exchange is True


@pytest.mark.asyncio
async def test_ticker_exposes_spread_for_risk_checks(service):
    market, _ = service
    ticker = await market.ticker("BTCUSDT")
    assert ticker.bid_price < ticker.ask_price
    spread = ticker.spread_fraction
    assert spread is not None and 0 < spread < Decimal("0.01")


@pytest.mark.asyncio
async def test_spread_is_none_when_book_is_unavailable(service):
    """Absent quotes must not silently look like a zero spread."""
    from app.binance.market_data import Ticker
    from app.core.time_utils import utc_now

    ticker = Ticker(
        symbol="BTCUSDT",
        price=Decimal("50000"),
        bid_price=None,
        ask_price=None,
        received_at=utc_now(),
    )
    assert ticker.spread_fraction is None


@pytest.mark.asyncio
async def test_unparsable_row_raises_rather_than_yielding_partial_data(service):
    market, mock = service

    async def broken(path, *, params=None, **kwargs):
        if path == "/api/v3/klines":
            return [["not", "a", "kline"]]
        return await mock.get(path, params=params, **kwargs)

    market._client.get = broken  # type: ignore[method-assign]
    with pytest.raises(BinanceRequestError):
        await market.klines("BTCUSDT", "1h", limit=1)
