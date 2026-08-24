"""Spot market data: klines, tickers, order book (§9).

Klines are converted into the same ``Candle`` shape the rest of the system
uses, and the exchange's own closed flag decides whether a candle may be used
as a feature input (§16) — wall-clock proximity never does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.binance.errors import BinanceRequestError
from app.binance.rest_client import BinanceRestClient
from app.config import Settings

# Weights per the current Binance Spot documentation; they are only a cost hint
# for the limiter, which enforces the exchange's own declared limits (§71).
WEIGHT_KLINES = 2
WEIGHT_TICKER = 2
WEIGHT_ORDER_BOOK = 5
WEIGHT_EXCHANGE_INFO = 20

MAX_KLINES_PER_REQUEST = 1000


@dataclass(frozen=True)
class Kline:
    """One OHLCV candle as returned by Binance.

    ``is_closed`` is derived from the candle's own close time against server
    time, mirroring the ``x`` flag on the WebSocket stream.
    """

    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    trades: int
    is_closed: bool

    @classmethod
    def from_rest_row(
        cls, row: list[Any], *, symbol: str, timeframe: str, now_ms: int
    ) -> Kline:
        """Parse one row of ``GET /api/v3/klines``.

        Binance returns close_time as the last millisecond *inside* the candle
        (open + interval - 1), so a candle is closed once server time has
        passed it.
        """
        try:
            open_ms = int(row[0])
            close_ms = int(row[6])
            return cls(
                symbol=symbol.upper(),
                timeframe=timeframe,
                open_time=_ms_to_utc(open_ms),
                close_time=_ms_to_utc(close_ms + 1),
                open=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal(str(row[5])),
                quote_volume=Decimal(str(row[7])),
                trades=int(row[8]),
                is_closed=now_ms > close_ms,
            )
        except (IndexError, TypeError, ValueError, ArithmeticError) as exc:
            raise BinanceRequestError(f"Unparsable kline row: {exc}") from exc


@dataclass(frozen=True)
class Ticker:
    symbol: str
    price: Decimal
    bid_price: Decimal | None
    ask_price: Decimal | None
    received_at: datetime

    @property
    def spread_fraction(self) -> Decimal | None:
        """Relative bid/ask spread, for the risk engine's spread protection."""
        if self.bid_price is None or self.ask_price is None:
            return None
        if self.bid_price <= 0:
            return None
        mid = (self.bid_price + self.ask_price) / 2
        return (self.ask_price - self.bid_price) / mid if mid > 0 else None


class MarketDataService:
    """Read-only Spot market data.  Contains no order-placing surface."""

    def __init__(self, client: BinanceRestClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def exchange_info(self, symbols: list[str] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if symbols:
            # Binance expects a JSON array literal for this parameter.
            joined = ",".join(f'"{symbol.upper()}"' for symbol in symbols)
            params["symbols"] = f"[{joined}]"
        payload = await self._client.get(
            "/api/v3/exchangeInfo", params=params, weight=WEIGHT_EXCHANGE_INFO
        )
        # Every response carries the live limits; feed them to the limiter (§71).
        self._client.rate_limiter.update_from_exchange_info(payload)
        return payload

    async def klines(
        self,
        symbol: str,
        timeframe: str,
        *,
        limit: int = 500,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[Kline]:
        if limit < 1 or limit > MAX_KLINES_PER_REQUEST:
            raise BinanceRequestError(
                f"limit must be between 1 and {MAX_KLINES_PER_REQUEST}, got {limit}."
            )
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": timeframe,
            "limit": limit,
        }
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms

        rows = await self._client.get(
            "/api/v3/klines", params=params, weight=WEIGHT_KLINES
        )
        if not isinstance(rows, list):
            raise BinanceRequestError("klines response was not a list.")

        now_ms = self._client.time_sync.timestamp_ms()
        return [
            Kline.from_rest_row(row, symbol=symbol, timeframe=timeframe, now_ms=now_ms)
            for row in rows
        ]

    async def closed_klines(
        self, symbol: str, timeframe: str, *, limit: int = 500
    ) -> list[Kline]:
        """Klines safe to use as feature inputs — the open candle is dropped (§16)."""
        return [
            kline
            for kline in await self.klines(symbol, timeframe, limit=limit)
            if kline.is_closed
        ]

    async def ticker(self, symbol: str) -> Ticker:
        payload = await self._client.get(
            "/api/v3/ticker/bookTicker",
            params={"symbol": symbol.upper()},
            weight=WEIGHT_TICKER,
        )
        price_payload = await self._client.get(
            "/api/v3/ticker/price",
            params={"symbol": symbol.upper()},
            weight=WEIGHT_TICKER,
        )
        from app.core.time_utils import utc_now

        return Ticker(
            symbol=symbol.upper(),
            price=Decimal(str(price_payload["price"])),
            bid_price=_optional_decimal(payload.get("bidPrice")),
            ask_price=_optional_decimal(payload.get("askPrice")),
            received_at=utc_now(),
        )

    async def order_book(self, symbol: str, *, limit: int = 100) -> dict[str, Any]:
        return await self._client.get(
            "/api/v3/depth",
            params={"symbol": symbol.upper(), "limit": limit},
            weight=WEIGHT_ORDER_BOOK,
        )


def _ms_to_utc(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None
