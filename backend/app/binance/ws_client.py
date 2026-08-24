"""Binance Spot market-data WebSocket client (§13, §44, §53).

Reconnects with bounded exponential backoff and marks data stale on
disconnect.  Stale data can never trigger a trade (§44), so the staleness flag
is part of the client's public surface rather than an internal detail.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from app.core.logging_config import get_logger
from app.core.time_utils import utc_now

logger = get_logger("binance.ws")

MAINNET_STREAM_URL = "wss://stream.binance.com:9443/stream"
TESTNET_STREAM_URL = "wss://stream.testnet.binance.vision/stream"

INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 60.0


@dataclass
class StreamState:
    """Observable connection state, surfaced to health and the frontend."""

    connected: bool = False
    last_message_at: str | None = None
    reconnects: int = 0
    last_error: str | None = None
    subscribed: tuple[str, ...] = field(default_factory=tuple)


class BinanceStreamClient:
    """Consumes combined Spot streams and dispatches decoded payloads."""

    def __init__(
        self,
        *,
        testnet: bool = True,
        on_message: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        url: str | None = None,
    ) -> None:
        self.url = url or (TESTNET_STREAM_URL if testnet else MAINNET_STREAM_URL)
        self._on_message = on_message
        self.state = StreamState()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    @staticmethod
    def kline_stream(symbol: str, timeframe: str) -> str:
        return f"{symbol.lower()}@kline_{timeframe}"

    @staticmethod
    def ticker_stream(symbol: str) -> str:
        return f"{symbol.lower()}@bookTicker"

    async def start(self, streams: list[str]) -> None:
        if self._task is not None and not self._task.done():
            raise RuntimeError("Stream client is already running.")
        self.state.subscribed = tuple(streams)
        self._stop.clear()
        self._task = asyncio.create_task(self._run(streams), name="binance-stream")

    async def stop(self) -> None:
        """Graceful shutdown — cancellation is awaited, never fire-and-forget (§93)."""
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.state.connected = False

    async def _run(self, streams: list[str]) -> None:
        backoff = INITIAL_BACKOFF_SECONDS
        url = f"{self.url}?streams={'/'.join(streams)}"

        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    url, ping_interval=20, ping_timeout=20, close_timeout=5
                ) as socket:
                    self.state.connected = True
                    self.state.last_error = None
                    backoff = INITIAL_BACKOFF_SECONDS
                    logger.info(
                        "Binance stream connected",
                        extra={
                            "event_type": "stream_connected",
                            "stream_count": len(streams),
                        },
                    )
                    await self._consume(socket)
            except asyncio.CancelledError:
                raise
            except (ConnectionClosed, OSError, websockets.WebSocketException) as exc:
                self.state.last_error = str(exc)
            except Exception as exc:
                self.state.last_error = str(exc)
                logger.exception(
                    "Unexpected error in Binance stream",
                    extra={"event_type": "stream_error"},
                )

            self.state.connected = False
            if self._stop.is_set():
                break

            self.state.reconnects += 1
            # Full jitter: without it, every stream reconnects in lockstep after
            # a shared outage and hammers the exchange (§53).
            delay = random.uniform(0, backoff)
            logger.warning(
                "Binance stream disconnected; reconnecting",
                extra={
                    "event_type": "stream_reconnect",
                    "delay_seconds": round(delay, 2),
                    "reconnects": self.state.reconnects,
                },
            )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
                break
            except TimeoutError:
                pass
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    async def _consume(self, socket: Any) -> None:
        async for raw in socket:
            if self._stop.is_set():
                return
            try:
                envelope = json.loads(raw)
            except (TypeError, ValueError):
                logger.warning(
                    "Discarding undecodable stream frame",
                    extra={"event_type": "stream_bad_frame"},
                )
                continue

            self.state.last_message_at = utc_now().isoformat()
            stream = envelope.get("stream")
            data = envelope.get("data")
            if not isinstance(stream, str) or not isinstance(data, dict):
                continue
            if self._on_message is not None:
                await self._on_message(stream, data)


def parse_kline_event(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a kline payload, or ``None`` if the frame is not a kline.

    The exchange's own ``x`` flag decides closure — this is the authoritative
    signal §16 requires, and it is never inferred from the clock.
    """
    kline = data.get("k")
    if not isinstance(kline, dict):
        return None
    try:
        return {
            "symbol": str(data.get("s", kline.get("s", ""))).upper(),
            "timeframe": str(kline["i"]),
            "open_time_ms": int(kline["t"]),
            "close_time_ms": int(kline["T"]),
            "open": str(kline["o"]),
            "high": str(kline["h"]),
            "low": str(kline["l"]),
            "close": str(kline["c"]),
            "volume": str(kline["v"]),
            "quote_volume": str(kline.get("q", "0")),
            "trades": int(kline.get("n", 0)),
            "is_closed": bool(kline["x"]),
        }
    except (KeyError, TypeError, ValueError):
        return None
