"""Exchange metadata: symbol rules and filters (§9, §33).

Order validation must use live exchange rules, never assumed values — Binance
rejects quantities and prices that violate a symbol's filters, and those
filters change.  This module is the only place they are interpreted.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.binance.errors import BinanceRequestError


@dataclass(frozen=True)
class SymbolFilters:
    """The filters this system enforces before an order is ever built.

    Fields are ``None`` when the exchange does not declare that filter for the
    symbol; callers must treat ``None`` as "no constraint", never as zero.
    """

    min_price: Decimal | None = None
    max_price: Decimal | None = None
    tick_size: Decimal | None = None
    min_qty: Decimal | None = None
    max_qty: Decimal | None = None
    step_size: Decimal | None = None
    min_notional: Decimal | None = None
    apply_min_to_market: bool = True

    @classmethod
    def from_symbol_payload(cls, payload: dict[str, Any]) -> SymbolFilters:
        by_type: dict[str, dict[str, Any]] = {}
        for entry in payload.get("filters", []) or []:
            if isinstance(entry, dict) and "filterType" in entry:
                by_type[str(entry["filterType"])] = entry

        price = by_type.get("PRICE_FILTER", {})
        lot = by_type.get("LOT_SIZE", {})
        # Binance has used both NOTIONAL and MIN_NOTIONAL over time; read
        # whichever the exchange actually sent rather than assuming one.
        notional = by_type.get("NOTIONAL") or by_type.get("MIN_NOTIONAL") or {}

        return cls(
            min_price=_decimal(price.get("minPrice")),
            max_price=_decimal(price.get("maxPrice")),
            tick_size=_decimal(price.get("tickSize")),
            min_qty=_decimal(lot.get("minQty")),
            max_qty=_decimal(lot.get("maxQty")),
            step_size=_decimal(lot.get("stepSize")),
            min_notional=_decimal(
                notional.get("minNotional") or notional.get("notional")
            ),
            apply_min_to_market=bool(
                notional.get("applyMinToMarket", notional.get("applyToMarket", True))
            ),
        )


@dataclass(frozen=True)
class SymbolInfo:
    """A tradable Spot symbol and the rules that govern orders on it."""

    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    base_precision: int
    quote_precision: int
    is_spot_trading_allowed: bool
    order_types: tuple[str, ...]
    filters: SymbolFilters
    raw_filters: tuple[dict[str, Any], ...]

    @property
    def tradable(self) -> bool:
        """Spot trading permitted right now.

        A symbol in any state other than TRADING (HALT, BREAK, delisted) is not
        tradable, and the trading engine must treat it as unavailable rather
        than attempting an order it knows will be rejected.
        """
        return self.status == "TRADING" and self.is_spot_trading_allowed

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SymbolInfo:
        try:
            return cls(
                symbol=str(payload["symbol"]).upper(),
                base_asset=str(payload["baseAsset"]).upper(),
                quote_asset=str(payload["quoteAsset"]).upper(),
                status=str(payload.get("status", "UNKNOWN")).upper(),
                base_precision=int(payload.get("baseAssetPrecision", 8)),
                quote_precision=int(payload.get("quoteAssetPrecision", 8)),
                is_spot_trading_allowed=bool(
                    payload.get("isSpotTradingAllowed", False)
                ),
                order_types=tuple(
                    str(item) for item in payload.get("orderTypes", []) or []
                ),
                filters=SymbolFilters.from_symbol_payload(payload),
                raw_filters=tuple(payload.get("filters", []) or []),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BinanceRequestError(
                f"Unparsable symbol payload from exchangeInfo: {exc}"
            ) from exc


class ExchangeMetadata:
    """In-memory view of ``exchangeInfo`` for the configured symbols."""

    def __init__(self) -> None:
        self._symbols: dict[str, SymbolInfo] = {}
        self.loaded_at: str | None = None

    def load(self, payload: dict[str, Any]) -> list[SymbolInfo]:
        symbols = [
            SymbolInfo.from_payload(entry)
            for entry in payload.get("symbols", []) or []
            if isinstance(entry, dict)
        ]
        self._symbols = {info.symbol: info for info in symbols}
        from app.core.time_utils import utc_now

        self.loaded_at = utc_now().isoformat()
        return symbols

    def get(self, symbol: str) -> SymbolInfo:
        try:
            return self._symbols[symbol.upper()]
        except KeyError as exc:
            raise BinanceRequestError(
                f"Symbol {symbol!r} is not present in exchange metadata."
            ) from exc

    def has(self, symbol: str) -> bool:
        return symbol.upper() in self._symbols

    @property
    def symbols(self) -> list[SymbolInfo]:
        return list(self._symbols.values())

    @property
    def is_loaded(self) -> bool:
        return bool(self._symbols)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None
    # Binance sends unused filter bounds as "0"; that means "no constraint",
    # and returning 0 would make every quantity look invalid.
    return parsed if parsed > 0 else None
