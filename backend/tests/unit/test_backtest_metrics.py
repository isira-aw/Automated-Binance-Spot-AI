"""Trading performance metrics (§41)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.backtesting.metrics import compute_metrics, max_drawdown, sharpe_ratio, sortino_ratio
from app.paper_trading.portfolio import ClosedTrade

D = Decimal
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def trade(net: str, *, gross: str | None = None, fees="0.1", slip="0.05") -> ClosedTrade:
    net_d = D(net)
    gross_d = D(gross) if gross else net_d + D(fees)
    return ClosedTrade(
        symbol="BTCUSDT", quantity=D("1"), entry_price=D("100"), exit_price=D("100") + net_d,
        entry_time=T0, exit_time=T0, gross_pnl=gross_d, fees=D(fees), slippage_cost=D(slip),
        net_pnl=net_d, return_pct=net_d / D("100"), exit_reason="EXIT",
    )


class TestDrawdown:
    def test_a_rising_curve_has_no_drawdown(self):
        assert max_drawdown([D("100"), D("110"), D("120")]) == pytest.approx(0.0)

    def test_drawdown_is_measured_peak_to_trough(self):
        assert max_drawdown([D("100"), D("120"), D("90"), D("110")]) == pytest.approx(0.25)

    def test_a_single_point_curve_is_undefined(self):
        assert max_drawdown([D("100")]) is None


class TestRatios:
    def test_a_flat_curve_has_no_defined_sharpe(self):
        """Zero volatility means no risk-adjusted return to speak of --
        reporting a number here would be a fabrication."""
        assert sharpe_ratio([D("100")] * 10, periods_per_year=365) is None

    def test_a_rising_volatile_curve_has_positive_sharpe(self):
        curve = [D("100"), D("102"), D("101"), D("104"), D("103"), D("106")]
        assert sharpe_ratio(curve, periods_per_year=365) > 0

    def test_a_falling_curve_has_negative_sharpe(self):
        curve = [D("100"), D("98"), D("99"), D("96"), D("97"), D("94")]
        assert sharpe_ratio(curve, periods_per_year=365) < 0

    def test_sortino_is_undefined_without_a_losing_period(self):
        """Undefined rather than infinite: there is no downside to divide by."""
        curve = [D("100"), D("101"), D("102"), D("103")]
        assert sortino_ratio(curve, periods_per_year=365) is None

    def test_sortino_penalises_only_downside(self):
        curve = [D("100"), D("105"), D("104"), D("110"), D("109"), D("115")]
        assert sortino_ratio(curve, periods_per_year=365) > 0

    def test_too_few_points_yields_none(self):
        assert sharpe_ratio([D("100")], periods_per_year=365) is None
        assert sortino_ratio([D("100")], periods_per_year=365) is None


class TestMetricSet:
    def test_no_trades_produces_a_zeroed_but_honest_result(self):
        m = compute_metrics([], [D("100")], initial_capital=D("100"))
        assert m.trade_count == 0
        assert m.win_rate is None  # not 0.0 -- there is nothing to average
        assert m.profit_factor is None

    def test_win_and_loss_counts_are_net_of_fees(self):
        m = compute_metrics(
            [trade("5"), trade("-3"), trade("2")], [D("100"), D("104")], initial_capital=D("100")
        )
        assert m.trade_count == 3
        assert m.win_count == 2
        assert m.loss_count == 1
        assert m.win_rate == pytest.approx(2 / 3)

    def test_profit_factor_is_gross_profit_over_gross_loss(self):
        m = compute_metrics(
            [trade("10"), trade("-5")], [D("100"), D("105")], initial_capital=D("100")
        )
        assert m.profit_factor == pytest.approx(2.0)

    def test_profit_factor_is_undefined_with_no_losses(self):
        """Not infinity, and not a large placeholder -- undefined."""
        m = compute_metrics([trade("10")], [D("100"), D("110")], initial_capital=D("100"))
        assert m.profit_factor is None

    def test_expectancy_is_the_average_net_outcome_per_trade(self):
        m = compute_metrics(
            [trade("10"), trade("-4")], [D("100"), D("106")], initial_capital=D("100")
        )
        assert m.expectancy == pytest.approx(D("3"))

    def test_fees_and_slippage_are_totalled_separately(self):
        m = compute_metrics([trade("5"), trade("5")], [D("100")], initial_capital=D("100"))
        assert m.total_fees == pytest.approx(D("0.2"))
        assert m.total_slippage == pytest.approx(D("0.1"))

    def test_a_high_win_rate_with_a_losing_expectancy_is_visible(self):
        """§41: win rate alone is never the objective. Nine small wins and one
        large loss must show a good win rate *and* a negative expectancy."""
        trades = [trade("1") for _ in range(9)] + [trade("-50")]
        m = compute_metrics(trades, [D("100"), D("59")], initial_capital=D("100"))
        assert m.win_rate == pytest.approx(0.9)
        assert m.expectancy < 0
        assert m.profit_factor < 1

    def test_exposure_is_the_fraction_of_bars_in_market(self):
        m = compute_metrics(
            [], [D("100")], initial_capital=D("100"), bars_in_market=30, total_bars=100
        )
        assert m.exposure == pytest.approx(0.3)

    def test_return_pct_is_measured_against_initial_capital(self):
        m = compute_metrics([], [D("100"), D("125")], initial_capital=D("100"))
        assert m.return_pct == pytest.approx(0.25)

    def test_to_dict_is_json_safe(self):
        import json

        m = compute_metrics([trade("5")], [D("100"), D("105")], initial_capital=D("100"))
        json.dumps(m.to_dict())  # must not raise on Decimal
