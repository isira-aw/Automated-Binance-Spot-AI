"""Symbol filters come from live exchange metadata, never assumed (§33)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.binance.errors import BinanceRequestError
from app.binance.exchange_metadata import ExchangeMetadata, SymbolFilters, SymbolInfo
from app.binance.mock import MockBinanceServer


def test_filters_are_parsed_from_payload():
    filters = SymbolFilters.from_symbol_payload(
        MockBinanceServer().symbol_payload("BTCUSDT")
    )
    assert filters.tick_size == Decimal("0.01000000")
    assert filters.step_size == Decimal("0.00001000")
    assert filters.min_notional == Decimal("5.00000000")


def test_zero_bounds_mean_no_constraint_not_zero():
    """Binance sends unused bounds as "0"; treating that as a real limit would
    make every quantity look invalid."""
    filters = SymbolFilters.from_symbol_payload(
        {
            "filters": [
                {
                    "filterType": "PRICE_FILTER",
                    "minPrice": "0",
                    "maxPrice": "0",
                    "tickSize": "0.01",
                },
                {"filterType": "LOT_SIZE", "minQty": "0", "maxQty": "0", "stepSize": "0.001"},
            ]
        }
    )
    assert filters.min_price is None
    assert filters.max_qty is None
    assert filters.tick_size == Decimal("0.01")


def test_both_notional_filter_names_are_accepted():
    """Binance has used MIN_NOTIONAL and NOTIONAL over time."""
    legacy = SymbolFilters.from_symbol_payload(
        {"filters": [{"filterType": "MIN_NOTIONAL", "minNotional": "10.0"}]}
    )
    current = SymbolFilters.from_symbol_payload(
        {"filters": [{"filterType": "NOTIONAL", "minNotional": "10.0"}]}
    )
    assert legacy.min_notional == current.min_notional == Decimal("10.0")


def test_missing_filters_yield_no_constraints():
    filters = SymbolFilters.from_symbol_payload({"filters": []})
    assert filters.min_notional is None
    assert filters.step_size is None


def test_symbol_is_not_tradable_unless_status_is_trading():
    payload = MockBinanceServer().symbol_payload("BTCUSDT")
    assert SymbolInfo.from_payload(payload).tradable is True

    for status in ("HALT", "BREAK", "END_OF_DAY"):
        halted = dict(payload, status=status)
        assert SymbolInfo.from_payload(halted).tradable is False


def test_symbol_is_not_tradable_when_spot_is_disallowed():
    payload = dict(MockBinanceServer().symbol_payload("BTCUSDT"), isSpotTradingAllowed=False)
    assert SymbolInfo.from_payload(payload).tradable is False


def test_unparsable_symbol_payload_raises():
    with pytest.raises(BinanceRequestError):
        SymbolInfo.from_payload({"symbol": "BTCUSDT"})


def test_metadata_lookup_is_case_insensitive():
    metadata = ExchangeMetadata()
    metadata.load(MockBinanceServer().exchange_info())
    assert metadata.get("btcusdt").symbol == "BTCUSDT"
    assert metadata.has("EthUsdt") is True


def test_unknown_symbol_raises_rather_than_returning_none():
    """A missing symbol must not degrade into a None that reaches order sizing."""
    metadata = ExchangeMetadata()
    metadata.load(MockBinanceServer().exchange_info())
    with pytest.raises(BinanceRequestError, match="not present"):
        metadata.get("DOGEUSDT")
