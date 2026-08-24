"""BinanceService — the single entry point to the exchange (§9).

    BinanceService
        ├── REST client
        ├── WebSocket client
        ├── Market data service
        └── Exchange metadata service

Account and order services are declared in the architecture but deliberately
absent here: Phase 5 is read-only market data.  Nothing in this module can
place, cancel or amend an order, and no withdrawal surface exists anywhere in
the system (§70).
"""

from __future__ import annotations

from typing import Any

from app.binance.errors import BinanceError
from app.binance.exchange_metadata import ExchangeMetadata, SymbolInfo
from app.binance.market_data import Kline, MarketDataService, Ticker
from app.binance.rest_client import BinanceRestClient
from app.binance.ws_client import BinanceStreamClient, StreamState
from app.config import Settings
from app.core.logging_config import get_logger
from app.core.time_utils import is_data_stale, utc_now
from app.models.enums import ComponentHealth

logger = get_logger("binance.service")


class BinanceService:
    """Coordinates the REST client, metadata cache and market-data streams."""

    def __init__(
        self,
        settings: Settings,
        *,
        rest_client: BinanceRestClient | None = None,
        stream_client: BinanceStreamClient | None = None,
    ) -> None:
        self._settings = settings
        self.rest = rest_client or BinanceRestClient(settings)
        self.metadata = ExchangeMetadata()
        self.market_data = MarketDataService(self.rest, settings)
        self.stream = stream_client or BinanceStreamClient(
            testnet=settings.binance.testnet
        )
        self.last_error: str | None = None
        self.connected = False

    # -- lifecycle --------------------------------------------------------

    async def connect(self) -> None:
        """Establish connectivity: ping, sync time, load metadata and limits.

        Raises :class:`BinanceError` on failure.  The caller decides whether
        that is fatal; market data being unavailable stops new trades but must
        not crash the application (§44).
        """
        await self.rest.ping()
        await self.rest.server_time_ms()
        payload = await self.market_data.exchange_info(self._settings.trading.assets)
        symbols = self.metadata.load(payload)
        self.connected = True
        self.last_error = None
        logger.info(
            "Binance connected",
            extra={
                "event_type": "binance_connected",
                "testnet": self._settings.binance.testnet,
                "symbol_count": len(symbols),
                "clock_offset_ms": self.rest.time_sync.offset_ms,
            },
        )

    async def close(self) -> None:
        await self.stream.stop()
        await self.rest.aclose()
        self.connected = False

    # -- reads ------------------------------------------------------------

    def symbol(self, symbol: str) -> SymbolInfo:
        return self.metadata.get(symbol)

    async def refresh_metadata(self) -> list[SymbolInfo]:
        payload = await self.market_data.exchange_info(self._settings.trading.assets)
        return self.metadata.load(payload)

    async def closed_klines(self, symbol: str, timeframe: str, *, limit: int = 500) -> list[Kline]:
        return await self.market_data.closed_klines(symbol, timeframe, limit=limit)

    async def ticker(self, symbol: str) -> Ticker:
        return await self.market_data.ticker(symbol)

    # -- health -----------------------------------------------------------

    def stream_state(self) -> StreamState:
        return self.stream.state

    def data_is_stale(self) -> bool:
        """Whether stream data has aged past the risk engine's threshold (§31).

        A stream that has never delivered a message counts as stale: absence of
        data is not evidence of fresh data.
        """
        last = self.stream.state.last_message_at
        if last is None:
            return True
        from datetime import datetime

        return is_data_stale(
            datetime.fromisoformat(last),
            self._settings.risk.stale_data_protection_seconds,
        )

    async def health(self) -> dict[str, Any]:
        """Component status for ``/system/health`` (§43, §105)."""
        if not self._settings.binance.testnet and not self._settings.binance.has_credentials:
            # Public market data needs no key, so this is not an error — but the
            # operator should know the client is unauthenticated.
            detail = "Connected without credentials (public market data only)."
        else:
            detail = None

        if not self.connected:
            return {
                "status": ComponentHealth.OFFLINE.value,
                "detail": self.last_error or "Not connected to Binance.",
            }

        failures = self.rest.consecutive_failures
        threshold = self._settings.risk.api_failure_protection_threshold
        if failures >= threshold:
            return {
                "status": ComponentHealth.ERROR.value,
                "detail": f"{failures} consecutive Binance API failures.",
                "consecutive_failures": failures,
            }

        status = ComponentHealth.ONLINE
        if failures > 0 or not self.rest.time_sync.synchronised:
            status = ComponentHealth.DEGRADED

        return {
            "status": status.value,
            "detail": detail,
            "testnet": self._settings.binance.testnet,
            "authenticated": self._settings.binance.has_credentials,
            "clock_offset_ms": self.rest.time_sync.offset_ms,
            "clock_synced_at": self.rest.time_sync.synced_at,
            "rate_limits_from_exchange": self.rest.rate_limiter.configured_from_exchange,
            "symbols_loaded": len(self.metadata.symbols),
            "consecutive_failures": failures,
            "checked_at": utc_now().isoformat(),
        }

    async def market_data_health(self) -> dict[str, Any]:
        """Separate probe for the streaming layer, which fails independently."""
        state = self.stream.state
        if not state.subscribed:
            return {
                "status": ComponentHealth.OFFLINE.value,
                "detail": "No market-data streams subscribed.",
            }
        if not state.connected:
            return {
                "status": ComponentHealth.ERROR.value,
                "detail": state.last_error or "Market-data stream disconnected.",
                "reconnects": state.reconnects,
            }
        if self.data_is_stale():
            # Explicit: stale data must never reach the trading path (§44).
            return {
                "status": ComponentHealth.DEGRADED.value,
                "detail": "Stream connected but data is stale; trading is blocked.",
                "last_message_at": state.last_message_at,
            }
        return {
            "status": ComponentHealth.ONLINE.value,
            "streams": len(state.subscribed),
            "last_message_at": state.last_message_at,
            "reconnects": state.reconnects,
        }


async def probe_error_detail(exc: BinanceError) -> dict[str, Any]:
    return {"status": ComponentHealth.ERROR.value, "detail": exc.message}
