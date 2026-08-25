"""Resolving exchange filters for sizing/rounding, with an honest fallback.

Shared by anything that needs to size an order without necessarily having a
live-connected Binance service on hand -- a backtest replaying history, or a
paper trade placed while Binance happens to be unreachable. The fallback is
"no constraint", never a guessed filter set standing in for real exchange
rules (§82/§96) -- callers get the fallback's provenance back so it can be
disclosed rather than silently assumed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.binance.exchange_metadata import SymbolFilters

if TYPE_CHECKING:
    from app.binance.service import BinanceService


def resolve_symbol_filters(
    binance_service: BinanceService | None, symbol: str
) -> tuple[SymbolFilters, str]:
    if binance_service is not None and binance_service.metadata.has(symbol):
        return binance_service.metadata.get(symbol).filters, "live exchange metadata"
    return SymbolFilters(), "default (no exchange metadata cached) -- no constraint applied"
