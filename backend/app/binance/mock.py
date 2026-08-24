"""Deterministic mock Binance connector for automated tests (§62, §63).

Real credentials are never used in tests and no test reaches the network.  The
generated data is reproducible from a seed so assertions cannot depend on live
market prices.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

from app.binance.errors import BinanceRequestError
from app.core.time_utils import timeframe_seconds

# A fixed, obviously-synthetic starting price per symbol.  These are test
# fixtures, not estimates of real value.
_BASE_PRICES = {"BTCUSDT": Decimal("50000"), "ETHUSDT": Decimal("3000"), "BNBUSDT": Decimal("400")}
_DEFAULT_BASE_PRICE = Decimal("100")


def _deterministic_offset(symbol: str, index: int) -> Decimal:
    """Reproducible pseudo-random walk step, stable across runs and machines."""
    digest = hashlib.sha256(f"{symbol}:{index}".encode()).digest()
    # Map the first two bytes onto [-1, 1).
    raw = int.from_bytes(digest[:2], "big")
    return (Decimal(raw) / Decimal(65535) - Decimal("0.5")) * 2


class MockBinanceServer:
    """In-memory stand-in for the Binance REST surface used by Tier 1."""

    def __init__(
        self,
        *,
        symbols: list[str] | None = None,
        server_time_ms: int = 1_700_000_000_000,
    ) -> None:
        self.symbols = [s.upper() for s in (symbols or list(_BASE_PRICES))]
        self.server_time_ms = server_time_ms
        self.request_log: list[tuple[str, dict[str, Any]]] = []
        # Set to raise from the next call, to exercise failure handling.
        self.fail_next: Exception | None = None

    def _record(self, path: str, params: dict[str, Any]) -> None:
        self.request_log.append((path, dict(params)))
        if self.fail_next is not None:
            error, self.fail_next = self.fail_next, None
            raise error

    # -- REST surface -----------------------------------------------------

    async def get(self, path: str, *, params: dict[str, Any] | None = None, **_: Any) -> Any:
        params = dict(params or {})
        self._record(path, params)

        if path == "/api/v3/ping":
            return {}
        if path == "/api/v3/time":
            return {"serverTime": self.server_time_ms}
        if path == "/api/v3/exchangeInfo":
            return self.exchange_info()
        if path == "/api/v3/klines":
            return self.klines(params)
        if path == "/api/v3/ticker/price":
            symbol = str(params["symbol"]).upper()
            return {"symbol": symbol, "price": str(self.price(symbol))}
        if path == "/api/v3/ticker/bookTicker":
            symbol = str(params["symbol"]).upper()
            price = self.price(symbol)
            spread = price * Decimal("0.0001")
            return {
                "symbol": symbol,
                "bidPrice": str(price - spread),
                "askPrice": str(price + spread),
            }
        if path == "/api/v3/depth":
            return self.order_book(str(params["symbol"]).upper())
        raise BinanceRequestError(f"Mock server has no handler for {path}.")

    # -- payload builders -------------------------------------------------

    def price(self, symbol: str) -> Decimal:
        return _BASE_PRICES.get(symbol.upper(), _DEFAULT_BASE_PRICE)

    def exchange_info(self) -> dict[str, Any]:
        return {
            "timezone": "UTC",
            "serverTime": self.server_time_ms,
            "rateLimits": [
                {
                    "rateLimitType": "REQUEST_WEIGHT",
                    "interval": "MINUTE",
                    "intervalNum": 1,
                    "limit": 6000,
                },
                {
                    "rateLimitType": "ORDERS",
                    "interval": "SECOND",
                    "intervalNum": 10,
                    "limit": 100,
                },
                {
                    "rateLimitType": "RAW_REQUESTS",
                    "interval": "MINUTE",
                    "intervalNum": 5,
                    "limit": 61000,
                },
            ],
            "symbols": [self.symbol_payload(symbol) for symbol in self.symbols],
        }

    def symbol_payload(self, symbol: str) -> dict[str, Any]:
        symbol = symbol.upper()
        quote = "USDT"
        base = symbol[: -len(quote)] if symbol.endswith(quote) else symbol
        return {
            "symbol": symbol,
            "status": "TRADING",
            "baseAsset": base,
            "quoteAsset": quote,
            "baseAssetPrecision": 8,
            "quoteAssetPrecision": 8,
            "isSpotTradingAllowed": True,
            "orderTypes": ["LIMIT", "MARKET", "STOP_LOSS_LIMIT"],
            "filters": [
                {
                    "filterType": "PRICE_FILTER",
                    "minPrice": "0.01000000",
                    "maxPrice": "1000000.00000000",
                    "tickSize": "0.01000000",
                },
                {
                    "filterType": "LOT_SIZE",
                    "minQty": "0.00001000",
                    "maxQty": "9000.00000000",
                    "stepSize": "0.00001000",
                },
                {
                    "filterType": "NOTIONAL",
                    "minNotional": "5.00000000",
                    "applyMinToMarket": True,
                },
            ],
        }

    def klines(self, params: dict[str, Any]) -> list[list[Any]]:
        symbol = str(params["symbol"]).upper()
        timeframe = str(params["interval"])
        limit = int(params.get("limit", 500))
        step_ms = timeframe_seconds(timeframe) * 1000

        # The most recent candle is still open, matching the live API.
        last_open = (self.server_time_ms // step_ms) * step_ms

        start_time = params.get("startTime")
        if start_time is not None:
            # Page forward from startTime, exactly like the real endpoint:
            # up to `limit` candles, stopping at the still-open present candle
            # rather than fabricating history that has not "happened" yet.
            first_open = (int(start_time) // step_ms) * step_ms
            span = max(0, (last_open - first_open) // step_ms) + 1
            open_times = [first_open + i * step_ms for i in range(min(limit, span))]
        else:
            open_times = [last_open - offset * step_ms for offset in range(limit - 1, -1, -1)]

        rows: list[list[Any]] = []
        for open_ms in open_times:
            index = open_ms // step_ms
            base = self.price(symbol)
            drift = _deterministic_offset(symbol, index) * base / Decimal(100)
            open_price = base + drift
            close_price = (
                open_price
                + _deterministic_offset(symbol, index + 1) * base / Decimal(200)
            )
            high = max(open_price, close_price) * Decimal("1.001")
            low = min(open_price, close_price) * Decimal("0.999")
            rows.append(
                [
                    open_ms,
                    f"{open_price:.8f}",
                    f"{high:.8f}",
                    f"{low:.8f}",
                    f"{close_price:.8f}",
                    "10.00000000",
                    open_ms + step_ms - 1,
                    f"{close_price * 10:.8f}",
                    100,
                    "5.00000000",
                    f"{close_price * 5:.8f}",
                    "0",
                ]
            )
        return rows

    def order_book(self, symbol: str) -> dict[str, Any]:
        price = self.price(symbol)
        spread = price * Decimal("0.0001")
        return {
            "lastUpdateId": 1,
            "bids": [[str(price - spread), "1.00000000"]],
            "asks": [[str(price + spread), "1.00000000"]],
        }


def kline_stream_frame(
    *,
    symbol: str,
    timeframe: str,
    open_time_ms: int,
    close: str = "50000.00",
    is_closed: bool = True,
) -> dict[str, Any]:
    """A stream frame shaped like Binance's combined-stream kline payload."""
    step_ms = timeframe_seconds(timeframe) * 1000
    return {
        "stream": f"{symbol.lower()}@kline_{timeframe}",
        "data": {
            "e": "kline",
            "E": open_time_ms + step_ms,
            "s": symbol.upper(),
            "k": {
                "t": open_time_ms,
                "T": open_time_ms + step_ms - 1,
                "s": symbol.upper(),
                "i": timeframe,
                "o": "49900.00",
                "c": close,
                "h": "50100.00",
                "l": "49800.00",
                "v": "12.5",
                "q": "620000.0",
                "n": 250,
                "x": is_closed,
            },
        },
    }
