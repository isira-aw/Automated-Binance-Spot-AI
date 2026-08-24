"""Position sizing against risk limits and exchange filters (§32, §33, §88)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.binance.exchange_metadata import SymbolFilters
from app.config.risk_config import RiskConfig
from app.risk.position_sizing import (
    REJECT_BELOW_MIN_NOTIONAL,
    REJECT_BELOW_MIN_QTY,
    REJECT_INSUFFICIENT_BALANCE,
    REJECT_NO_EQUITY,
    REJECT_NO_STOP_DISTANCE,
    REJECT_TRADE_NOT_ECONOMIC,
    calculate_position_size,
)

D = Decimal


def permissive_filters(**overrides) -> SymbolFilters:
    """Filters that constrain nothing, so a test isolates one rule at a time."""
    base = {
        "min_qty": D("0.00000001"),
        "step_size": D("0.00000001"),
        "min_notional": D("0"),
        "max_qty": None,
    }
    base.update(overrides)
    return SymbolFilters(**base)


def size(**overrides):
    params = {
        "equity": D("1000"),
        "available_quote": D("1000"),
        "entry_price": D("100"),
        "stop_price": D("95"),
        "risk": RiskConfig(),
        "filters": permissive_filters(),
        "taker_fee": D("0.001"),
    }
    params.update(overrides)
    return calculate_position_size(**params)


class TestRiskPerTrade:
    def test_quantity_risks_exactly_the_configured_fraction(self):
        """1% of 1000 equity = 10 risked; stop is 5 away, so 2 units."""
        result = size(risk=RiskConfig(max_risk_per_trade=D("0.01")))
        assert result.approved
        assert result.quantity == pytest.approx(D("2"))
        assert result.risk_amount == pytest.approx(D("10"))

    def test_a_tighter_stop_allows_a_larger_position_for_the_same_risk(self):
        """Both stops are wide enough that the exposure caps do not bind, so
        this isolates the risk-sizing rule itself."""
        wide = size(stop_price=D("90"))   # 10 away -> 1 unit,   notional 100
        tight = size(stop_price=D("96"))  # 4 away  -> 2.5 units, notional 250
        assert tight.quantity > wide.quantity
        # Both risk the same amount -- that is the point of the rule.
        assert tight.risk_amount == pytest.approx(wide.risk_amount)

    def test_the_position_size_cap_overrides_equal_risk_sizing(self):
        """A very tight stop would size a position larger than the exposure
        cap allows; the cap wins, so the trade ends up risking *less* than
        max_risk_per_trade rather than exceeding max_position_size."""
        capped = size(stop_price=D("99"), risk=RiskConfig(max_position_size=D("0.35")))
        assert capped.approved
        assert capped.notional <= D("1000") * D("0.35")
        assert capped.risk_amount < D("1000") * RiskConfig().max_risk_per_trade

    def test_risked_amount_never_exceeds_the_cap_after_step_rounding(self):
        """Rounding is down, never nearest, so risk can only come in under."""
        result = size(filters=permissive_filters(step_size=D("0.1")))
        assert result.approved
        assert result.risk_amount <= D("1000") * RiskConfig().max_risk_per_trade


class TestExposureCaps:
    def test_position_size_cap_binds_before_risk_sizing(self):
        """A very tight stop would otherwise size a huge position."""
        result = size(
            stop_price=D("99.99"),
            risk=RiskConfig(max_position_size=D("0.2"), max_risk_per_trade=D("0.01")),
        )
        assert result.approved
        assert result.notional <= D("1000") * D("0.2")
        assert result.details["binding_cap"] == "max_position_size"

    def test_existing_asset_exposure_reduces_available_headroom(self):
        result = size(
            stop_price=D("99.9"),
            current_asset_exposure=D("400"),
            risk=RiskConfig(max_asset_exposure=D("0.5"), max_position_size=D("1")),
        )
        assert result.approved
        # 50% of 1000 = 500 cap, 400 already used -> at most 100 more.
        assert result.notional <= D("100")

    def test_a_filled_asset_cap_rejects_as_not_economic(self):
        result = size(
            current_asset_exposure=D("500"),
            risk=RiskConfig(max_asset_exposure=D("0.5")),
        )
        assert not result.approved
        assert result.reason_code == REJECT_TRADE_NOT_ECONOMIC

    def test_portfolio_cap_binds_across_all_assets(self):
        result = size(
            stop_price=D("99.9"),
            current_portfolio_exposure=D("750"),
            risk=RiskConfig(max_portfolio_exposure=D("0.8"), max_position_size=D("1")),
        )
        assert result.approved
        assert result.notional <= D("50")


class TestExchangeFilters:
    def test_quantity_is_rounded_down_onto_the_step_grid(self):
        result = size(filters=permissive_filters(step_size=D("0.5")))
        assert result.approved
        assert result.quantity % D("0.5") == 0

    def test_below_minimum_quantity_is_rejected(self):
        result = size(filters=permissive_filters(min_qty=D("100")))
        assert not result.approved
        assert result.reason_code == REJECT_BELOW_MIN_QTY

    def test_below_minimum_notional_is_rejected_with_the_small_account_note(self):
        """§88: this is the expected outcome on a small account, not an error."""
        result = size(
            equity=D("40"),
            available_quote=D("40"),
            filters=permissive_filters(min_notional=D("10")),
        )
        assert not result.approved
        assert result.reason_code == REJECT_BELOW_MIN_NOTIONAL
        assert "§88" in result.reason

    def test_min_notional_is_ignored_when_the_exchange_says_it_does_not_apply(self):
        result = size(
            equity=D("40"),
            available_quote=D("40"),
            filters=permissive_filters(min_notional=D("10"), apply_min_to_market=False),
        )
        assert result.approved

    def test_max_quantity_caps_the_position(self):
        result = size(filters=permissive_filters(max_qty=D("1")))
        assert result.approved
        assert result.quantity <= D("1")

    def test_rounding_to_zero_is_rejected_not_forced_to_the_minimum(self):
        result = size(
            equity=D("10"), available_quote=D("10"), filters=permissive_filters(step_size=D("1"))
        )
        assert not result.approved
        assert result.reason_code == REJECT_TRADE_NOT_ECONOMIC


class TestEconomicViability:
    def test_round_trip_fees_exceeding_risk_are_rejected(self):
        """§86: an edge smaller than its own transaction costs is not a trade."""
        result = size(taker_fee=D("0.05"))  # absurd 5% fee
        assert not result.approved
        assert result.reason_code == REJECT_TRADE_NOT_ECONOMIC
        assert "fees" in result.reason.lower()

    def test_insufficient_balance_is_rejected(self):
        result = size(available_quote=D("1"), equity=D("1000"), filters=permissive_filters())
        assert not result.approved
        assert result.reason_code in {REJECT_INSUFFICIENT_BALANCE, REJECT_TRADE_NOT_ECONOMIC}

    def test_fee_is_estimated_and_reported(self):
        result = size()
        assert result.approved
        assert result.estimated_fee == pytest.approx(result.notional * D("0.001"))


class TestPreconditions:
    def test_zero_equity_is_rejected(self):
        assert size(equity=D("0")).reason_code == REJECT_NO_EQUITY

    def test_missing_stop_is_rejected_rather_than_sized_arbitrarily(self):
        assert size(stop_price=None).reason_code == REJECT_NO_STOP_DISTANCE

    def test_a_stop_at_or_above_entry_is_rejected(self):
        assert size(stop_price=D("100")).reason_code == REJECT_NO_STOP_DISTANCE
        assert size(stop_price=D("105")).reason_code == REJECT_NO_STOP_DISTANCE

    def test_no_rejection_ever_returns_a_tradeable_quantity(self):
        """A rejected size must be unusable, so a caller that ignores the flag
        still cannot place an order from it."""
        for bad in (size(equity=D("0")), size(stop_price=None), size(taker_fee=D("0.05"))):
            assert not bad.approved
            assert bad.quantity == 0
