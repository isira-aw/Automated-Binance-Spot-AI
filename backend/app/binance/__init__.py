"""Binance Spot integration (§9).

Spot market data only in Phase 5.  There is no order-placing and no withdrawal
surface anywhere in this package (§70).
"""

from app.binance.errors import (
    BinanceAuthError,
    BinanceError,
    BinanceRateLimitError,
    BinanceRequestError,
    BinanceServerError,
    BinanceTimestampError,
    BinanceTransportError,
)
from app.binance.exchange_metadata import ExchangeMetadata, SymbolFilters, SymbolInfo
from app.binance.market_data import Kline, MarketDataService, Ticker
from app.binance.rate_limiter import RateLimiter, RateLimitRule
from app.binance.rest_client import BinanceRestClient
from app.binance.service import BinanceService
from app.binance.time_sync import TimeSync
from app.binance.ws_client import BinanceStreamClient, StreamState, parse_kline_event

__all__ = [
    "BinanceAuthError",
    "BinanceError",
    "BinanceRateLimitError",
    "BinanceRequestError",
    "BinanceRestClient",
    "BinanceServerError",
    "BinanceService",
    "BinanceStreamClient",
    "BinanceTimestampError",
    "BinanceTransportError",
    "ExchangeMetadata",
    "Kline",
    "MarketDataService",
    "RateLimitRule",
    "RateLimiter",
    "StreamState",
    "SymbolFilters",
    "SymbolInfo",
    "Ticker",
    "TimeSync",
    "parse_kline_event",
]
