"""Bridges Binance market-data streams onto the WebSocket event bus (§13).

Publishes ``ticker_update`` for every book update and ``candle_closed`` only
when the exchange itself marks the candle closed (§16).  An open candle is
never published as closed, because downstream feature building treats
``candle_closed`` as permission to use the bar — doing otherwise would leak
future information into a decision (§18).
"""

from __future__ import annotations

from typing import Any

from app.binance.market_data import Kline
from app.binance.service import BinanceService
from app.binance.ws_client import BinanceStreamClient, parse_kline_event
from app.config import Settings
from app.core.events import Event, EventType
from app.core.logging_config import get_logger
from app.database.session import session_scope
from app.services.historical_ingestion import persist_closed_candle
from app.technical.feature_engine import compute_latest
from app.websocket.event_bus import EventBus

logger = get_logger("workers.market_stream")


class MarketStreamBridge:
    """Translates raw stream frames into domain events."""

    def __init__(self, bus: EventBus, settings: Settings) -> None:
        self._bus = bus
        self._settings = settings
        self.closed_candles = 0
        self.ticker_updates = 0

    def streams(self) -> list[str]:
        """Stream names for every configured symbol and timeframe."""
        names: list[str] = []
        for symbol in self._settings.trading.assets:
            names.append(BinanceStreamClient.ticker_stream(symbol))
            for timeframe in self._settings.trading.timeframes:
                names.append(BinanceStreamClient.kline_stream(symbol, timeframe.value))
        return names

    async def handle(self, stream: str, data: dict[str, Any]) -> None:
        if "@kline_" in stream:
            await self._handle_kline(data)
        elif "@bookTicker" in stream:
            await self._handle_ticker(data)

    async def _handle_kline(self, data: dict[str, Any]) -> None:
        event = parse_kline_event(data)
        if event is None:
            return
        if not event["is_closed"]:
            # In-progress candles are intentionally not published: nothing
            # downstream may act on a bar that can still change.
            return
        self.closed_candles += 1

        await self._persist_and_compute_features(event)

        await self._bus.publish(
            Event.of(
                EventType.CANDLE_CLOSED,
                symbol=event["symbol"],
                timeframe=event["timeframe"],
                open_time_ms=event["open_time_ms"],
                close_time_ms=event["close_time_ms"],
                open=event["open"],
                high=event["high"],
                low=event["low"],
                close=event["close"],
                volume=event["volume"],
                trades=event["trades"],
            )
        )

    async def _persist_and_compute_features(self, event: dict[str, Any]) -> None:
        """Store the closed candle and refresh its feature vector.

        A failure here must not stop the stream: a websocket-side event still
        publishes even if this fails, so the frontend keeps seeing live prices
        while the persistence problem is logged for investigation -- losing
        one candle's features is recoverable (the next backfill or live candle
        fixes it), losing the whole stream connection is not (§44).
        """
        try:
            kline = Kline.from_stream_event(event)
        except Exception as exc:
            logger.warning(
                "Discarding an unparsable closed-candle stream event",
                extra={"event_type": "stream_candle_unparsable"},
                exc_info=exc,
            )
            return

        try:
            async with session_scope() as session:
                await persist_closed_candle(session, kline)
                await compute_latest(
                    session,
                    symbol=kline.symbol,
                    timeframe=kline.timeframe,
                    feature_version=self._settings.models.feature_version,
                )
        except Exception as exc:
            logger.error(
                "Failed to persist a closed candle or compute its features",
                extra={
                    "event_type": "stream_candle_persist_failed",
                    "symbol": kline.symbol,
                    "timeframe": kline.timeframe,
                },
                exc_info=exc,
            )

    async def _handle_ticker(self, data: dict[str, Any]) -> None:
        symbol = data.get("s")
        bid = data.get("b")
        ask = data.get("a")
        if not isinstance(symbol, str) or bid is None or ask is None:
            return
        self.ticker_updates += 1
        await self._bus.publish(
            Event.of(
                EventType.TICKER_UPDATE,
                symbol=symbol.upper(),
                bid=str(bid),
                ask=str(ask),
                bid_qty=str(data.get("B", "")),
                ask_qty=str(data.get("A", "")),
            )
        )


async def start_market_streams(
    service: BinanceService, bus: EventBus, settings: Settings
) -> MarketStreamBridge:
    """Subscribe to the configured streams and begin publishing events."""
    bridge = MarketStreamBridge(bus, settings)
    service.stream._on_message = bridge.handle  # type: ignore[attr-defined]
    streams = bridge.streams()
    await service.stream.start(streams)
    logger.info(
        "Market data streams started",
        extra={"event_type": "market_streams_started", "stream_count": len(streams)},
    )
    return bridge
