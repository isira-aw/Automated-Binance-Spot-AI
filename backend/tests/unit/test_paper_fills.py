"""Fill simulation: slippage, fees, partial fills, exits (§11B, §82, §83, §87)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import OrderSide
from app.paper_trading.fills import (
    apply_slippage,
    exit_reason_for_bar,
    simulate_fill,
    update_trailing_stop,
)

D = Decimal


class TestSlippage:
    def test_a_buy_always_fills_higher(self):
        assert apply_slippage(D("100"), OrderSide.BUY, D("10")) == D("100.1")

    def test_a_sell_always_fills_lower(self):
        assert apply_slippage(D("100"), OrderSide.SELL, D("10")) == D("99.9")

    def test_slippage_never_favours_the_trader(self):
        """§82: slippage that sometimes helps turns an execution cost into a
        coin flip and flatters results across many trades."""
        for bps in (D("1"), D("5"), D("50"), D("500")):
            assert apply_slippage(D("100"), OrderSide.BUY, bps) >= D("100")
            assert apply_slippage(D("100"), OrderSide.SELL, bps) <= D("100")


class TestFills:
    def test_a_full_fill_charges_fees_on_the_filled_value(self):
        result = simulate_fill(
            requested_quantity=D("2"),
            reference_price=D("100"),
            side=OrderSide.BUY,
            fee_rate=D("0.001"),
            slippage_bps=D("0"),
        )
        assert result.filled_quantity == D("2")
        assert result.fee == pytest.approx(D("0.2"))
        assert not result.is_partial

    def test_fees_are_always_charged(self):
        """§87: there is no zero-cost path through the fill model."""
        result = simulate_fill(
            requested_quantity=D("1"),
            reference_price=D("100"),
            side=OrderSide.BUY,
            fee_rate=D("0.001"),
            slippage_bps=D("5"),
        )
        assert result.fee > 0
        assert result.slippage_cost > 0

    def test_limited_liquidity_produces_a_partial_fill(self):
        result = simulate_fill(
            requested_quantity=D("10"),
            reference_price=D("100"),
            side=OrderSide.BUY,
            fee_rate=D("0.001"),
            slippage_bps=D("0"),
            available_liquidity=D("3"),
        )
        assert result.filled_quantity == D("3")
        assert result.is_partial

    def test_quantity_is_rounded_down_to_the_step_size(self):
        result = simulate_fill(
            requested_quantity=D("1.27"),
            reference_price=D("100"),
            side=OrderSide.BUY,
            fee_rate=D("0"),
            slippage_bps=D("0"),
            step_size=D("0.5"),
        )
        assert result.filled_quantity == D("1.0")

    def test_a_sub_step_quantity_fills_nothing_rather_than_rounding_up(self):
        result = simulate_fill(
            requested_quantity=D("0.4"),
            reference_price=D("100"),
            side=OrderSide.BUY,
            fee_rate=D("0"),
            slippage_bps=D("0"),
            step_size=D("1"),
        )
        assert result.is_empty

    def test_zero_or_negative_inputs_fill_nothing(self):
        for qty, price in ((D("0"), D("100")), (D("-1"), D("100")), (D("1"), D("0"))):
            result = simulate_fill(
                requested_quantity=qty,
                reference_price=price,
                side=OrderSide.BUY,
                fee_rate=D("0.001"),
                slippage_bps=D("5"),
            )
            assert result.is_empty


class TestExitDetection:
    def test_a_bar_touching_the_stop_exits_at_the_stop(self):
        assert exit_reason_for_bar(
            high=D("105"), low=D("94"), stop_loss=D("95"), take_profit=D("110")
        ) == "STOP_LOSS"

    def test_a_bar_touching_the_target_exits_at_the_target(self):
        assert exit_reason_for_bar(
            high=D("111"), low=D("99"), stop_loss=D("95"), take_profit=D("110")
        ) == "TAKE_PROFIT"

    def test_a_bar_spanning_both_reports_the_stop(self):
        """§82: intrabar order is unknowable from OHLC. Assuming the
        favourable one is exactly how a backtest manufactures profits that
        never existed."""
        assert exit_reason_for_bar(
            high=D("115"), low=D("90"), stop_loss=D("95"), take_profit=D("110")
        ) == "STOP_LOSS"

    def test_a_quiet_bar_produces_no_exit(self):
        assert exit_reason_for_bar(
            high=D("105"), low=D("99"), stop_loss=D("95"), take_profit=D("110")
        ) is None

    def test_no_exit_when_neither_level_is_set(self):
        assert (
            exit_reason_for_bar(high=D("999"), low=D("1"), stop_loss=None, take_profit=None)
            is None
        )


class TestTrailingStop:
    def test_the_stop_rises_with_a_new_high(self):
        assert update_trailing_stop(
            current_stop=D("95"), high=D("110"), trailing_distance=D("5")
        ) == D("105")

    def test_the_stop_never_falls(self):
        """A trailing stop that can move down is not a trailing stop -- it
        would let a position give back more than the trail permits."""
        assert update_trailing_stop(
            current_stop=D("105"), high=D("100"), trailing_distance=D("5")
        ) == D("105")

    def test_no_trailing_distance_leaves_the_stop_untouched(self):
        assert update_trailing_stop(
            current_stop=D("95"), high=D("200"), trailing_distance=None
        ) == D("95")

    def test_an_unset_stop_is_initialised_from_the_high(self):
        assert update_trailing_stop(
            current_stop=None, high=D("110"), trailing_distance=D("5")
        ) == D("105")
