"""Stream-to-event-bus bridge (§13, §16, §18)."""

from __future__ import annotations

import pytest

from app.binance.mock import kline_stream_frame
from app.core.events import EventType
from app.websocket.event_bus import EventBus
from app.workers.market_stream import MarketStreamBridge
from tests.conftest import make_settings


@pytest.fixture
def bridge() -> tuple[MarketStreamBridge, EventBus]:
    bus = EventBus(queue_size=64)
    return MarketStreamBridge(bus, make_settings()), bus


def test_streams_cover_every_symbol_and_timeframe(bridge):
    worker, _ = bridge
    settings = make_settings()
    names = worker.streams()
    expected = len(settings.trading.assets) * (1 + len(settings.trading.timeframes))
    assert len(names) == expected
    assert "btcusdt@kline_4h" in names
    assert "btcusdt@bookTicker" in names


@pytest.mark.asyncio
async def test_closed_candle_publishes_candle_closed(bridge):
    worker, bus = bridge
    async with bus.subscribe({EventType.CANDLE_CLOSED}) as subscriber:
        frame = kline_stream_frame(
            symbol="BTCUSDT", timeframe="4h", open_time_ms=1_700_000_000_000
        )
        await worker.handle(frame["stream"], frame["data"])
        event = subscriber.queue.get_nowait()

    assert event.event is EventType.CANDLE_CLOSED
    assert event.data["symbol"] == "BTCUSDT"
    assert event.data["timeframe"] == "4h"
    assert worker.closed_candles == 1


@pytest.mark.asyncio
async def test_open_candle_publishes_nothing(bridge):
    """The §18 guard at the transport edge: an in-progress bar must not be
    announced as closed, because downstream treats the event as permission to
    use it as a feature."""
    worker, bus = bridge
    async with bus.subscribe({EventType.CANDLE_CLOSED}) as subscriber:
        frame = kline_stream_frame(
            symbol="BTCUSDT", timeframe="4h", open_time_ms=1_700_000_000_000, is_closed=False
        )
        await worker.handle(frame["stream"], frame["data"])
        assert subscriber.queue.empty()
    assert worker.closed_candles == 0


@pytest.mark.asyncio
async def test_book_ticker_publishes_ticker_update(bridge):
    worker, bus = bridge
    async with bus.subscribe({EventType.TICKER_UPDATE}) as subscriber:
        await worker.handle(
            "btcusdt@bookTicker",
            {"s": "BTCUSDT", "b": "49999.00", "a": "50001.00", "B": "1.0", "A": "2.0"},
        )
        event = subscriber.queue.get_nowait()
    assert event.data["symbol"] == "BTCUSDT"
    assert event.data["bid"] == "49999.00"
    assert worker.ticker_updates == 1


@pytest.mark.asyncio
async def test_malformed_ticker_is_ignored(bridge):
    worker, bus = bridge
    async with bus.subscribe({EventType.TICKER_UPDATE}) as subscriber:
        await worker.handle("btcusdt@bookTicker", {"s": "BTCUSDT"})
        assert subscriber.queue.empty()
    assert worker.ticker_updates == 0


@pytest.mark.asyncio
async def test_unrecognised_stream_is_ignored(bridge):
    worker, bus = bridge
    async with bus.subscribe() as subscriber:
        await worker.handle("btcusdt@depth", {"anything": True})
        assert subscriber.queue.empty()
