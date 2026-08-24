"""Stream parsing and the closed-candle flag that gates feature building (§16)."""

from __future__ import annotations

import pytest

from app.binance.mock import kline_stream_frame
from app.binance.ws_client import BinanceStreamClient, parse_kline_event


def test_stream_names_follow_binance_conventions():
    assert BinanceStreamClient.kline_stream("BTCUSDT", "4h") == "btcusdt@kline_4h"
    assert BinanceStreamClient.ticker_stream("ETHUSDT") == "ethusdt@bookTicker"


def test_closed_flag_comes_from_the_exchange_not_the_clock():
    """§16 requires the exchange's own flag to decide closure."""
    closed = parse_kline_event(
        kline_stream_frame(symbol="BTCUSDT", timeframe="1h", open_time_ms=1_700_000_000_000)["data"]
    )
    still_open = parse_kline_event(
        kline_stream_frame(
            symbol="BTCUSDT", timeframe="1h", open_time_ms=1_700_000_000_000, is_closed=False
        )["data"]
    )
    assert closed is not None and closed["is_closed"] is True
    assert still_open is not None and still_open["is_closed"] is False


def test_parsed_event_carries_the_fields_feature_building_needs():
    event = parse_kline_event(
        kline_stream_frame(
            symbol="ETHUSDT", timeframe="15m", open_time_ms=1_700_000_000_000
        )["data"]
    )
    assert event is not None
    assert event["symbol"] == "ETHUSDT"
    assert event["timeframe"] == "15m"
    assert set(event) >= {"open", "high", "low", "close", "volume", "open_time_ms", "is_closed"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"k": "not-a-dict"},
        {"k": {"t": 1}},
        {"e": "bookTicker", "s": "BTCUSDT"},
    ],
)
def test_non_kline_or_malformed_frames_return_none(payload):
    """A malformed frame must be discarded, never turned into a partial candle."""
    assert parse_kline_event(payload) is None


def test_initial_state_reports_no_data():
    """A stream that has never delivered must not look fresh."""
    client = BinanceStreamClient(testnet=True)
    assert client.state.connected is False
    assert client.state.last_message_at is None
    assert client.state.reconnects == 0


def test_testnet_flag_selects_the_stream_endpoint():
    from app.binance.ws_client import MAINNET_STREAM_URL, TESTNET_STREAM_URL

    assert BinanceStreamClient(testnet=True).url == TESTNET_STREAM_URL
    assert BinanceStreamClient(testnet=False).url == MAINNET_STREAM_URL


@pytest.mark.asyncio
async def test_stop_is_safe_before_start():
    await BinanceStreamClient(testnet=True).stop()
