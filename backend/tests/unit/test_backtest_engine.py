"""Backtesting engine: no future data, real costs, shared components (§35, §82)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtesting.engine import BacktestEngine, HistoricalBar, StrategyDecision
from app.binance.exchange_metadata import SymbolFilters
from app.config.risk_config import RiskConfig

D = Decimal
T0 = datetime(2024, 1, 1, tzinfo=UTC)
FILTERS = SymbolFilters(min_qty=D("0.00000001"), step_size=D("0.00000001"), min_notional=D("0"))


def bars(closes: list[str], *, spread="1") -> list[HistoricalBar]:
    return [
        HistoricalBar(
            timestamp=T0 + timedelta(hours=i),
            open=D(c),
            high=D(c) + D(spread),
            low=D(c) - D(spread),
            close=D(c),
        )
        for i, c in enumerate(closes)
    ]


def engine(capital="10000", **risk_over):
    return BacktestEngine(
        symbol="BTCUSDT", timeframe="1h", initial_capital=D(capital),
        risk=RiskConfig(**risk_over), fee_rate=D("0.001"), slippage_bps=D("5"),
        filters=FILTERS,
    )


def never_trade(_history):
    return None


class TestLookaheadPrevention:
    def test_the_strategy_only_ever_sees_bars_up_to_the_current_one(self):
        """§82's core guarantee, enforced by the call signature: the full
        series is never passed, so a strategy cannot peek even by accident."""
        series = bars(["100"] * 20)
        seen_lengths: list[int] = []
        seen_last_timestamps: list[datetime] = []

        def recorder(history):
            seen_lengths.append(len(history))
            seen_last_timestamps.append(history[-1].timestamp)
            return None

        engine().run(series, recorder)

        assert seen_lengths == list(range(1, 21))
        # The last bar a strategy sees is always the bar being decided on.
        assert seen_last_timestamps == [bar.timestamp for bar in series]

    def test_a_strategy_cannot_reach_a_future_bar(self):
        """A strategy that tries to index past its history gets an error,
        not tomorrow's price."""
        series = bars(["100"] * 10)
        errors: list[str] = []

        def peeker(history):
            try:
                _ = history[len(history)]  # the *next* bar
            except IndexError:
                errors.append("blocked")
            return None

        engine().run(series, peeker)
        assert len(errors) == 10


class TestExecutionRealism:
    def test_a_flat_market_round_trip_loses_money_to_costs(self):
        """§87: fees and slippage are always applied; break-even is a loss."""
        series = bars(["100"] * 10)
        state = {"bought": False}

        def buy_once(history):
            if not state["bought"] and len(history) == 2:
                state["bought"] = True
                return StrategyDecision(action="BUY", stop_price=D("90"))
            return None

        result = engine().run(series, buy_once)
        assert result.metrics.trade_count == 1
        assert result.metrics.net_pnl < 0
        assert result.metrics.total_fees > 0

    def test_a_stop_is_hit_at_the_stop_price_not_the_close(self):
        """A stop that only triggers on the close would understate every gap."""
        series = [
            *bars(["100", "100", "100"]),
            HistoricalBar(
                timestamp=T0 + timedelta(hours=3), open=D("100"),
                high=D("100"), low=D("80"), close=D("99"),
            ),
        ]
        state = {"done": False}

        def buy_once(history):
            if not state["done"] and len(history) == 1:
                state["done"] = True
                return StrategyDecision(action="BUY", stop_price=D("95"))
            return None

        result = engine().run(series, buy_once)
        assert result.metrics.trade_count == 1
        trade = result.trades[0]
        assert trade.exit_reason == "STOP_LOSS"
        # Exited near 95, not at the bar's 99 close.
        assert trade.exit_price < D("96")

    def test_open_positions_are_closed_at_the_end_of_the_window(self):
        """A result must reflect realised outcomes, not an open paper gain."""
        series = bars(["100", "105", "110"])
        state = {"done": False}

        def buy_once(history):
            if not state["done"]:
                state["done"] = True
                return StrategyDecision(action="BUY", stop_price=D("90"))
            return None

        result = engine().run(series, buy_once)
        assert result.trades[-1].exit_reason == "BACKTEST_END"
        assert result.metrics.trade_count == 1


class TestRiskEngineIsShared:
    def test_tightening_a_risk_limit_changes_the_backtest_outcome(self):
        """§35: the backtest reuses the *same* risk engine, so a limit that
        would block live trading blocks a backtest identically. Proven by
        changing only the config and observing a different result -- if the
        backtest had its own sizing path, this would be unaffected."""
        series = bars(["100"] * 10)

        def always_buy(_history):
            return StrategyDecision(action="BUY", stop_price=D("95"))

        normal = engine().run(series, always_buy)
        tighter = engine(max_risk_per_trade=D("0.001")).run(series, always_buy)

        assert normal.metrics.trade_count == 1
        assert tighter.metrics.trade_count == 1
        # Same strategy, same bars, same fees -- only the risk config differs,
        # and the position is ten times smaller because the backtest sizes
        # through the very same code path live trading would use.
        assert tighter.trades[0].quantity < normal.trades[0].quantity
        assert tighter.trades[0].quantity == pytest.approx(
            normal.trades[0].quantity / 10, rel=D("0.01")
        )

    def test_only_one_position_is_held_at_a_time(self):
        series = bars(["100"] * 10)

        def always_buy(_history):
            return StrategyDecision(action="BUY", stop_price=D("95"))

        result = engine().run(series, always_buy)
        assert result.metrics.trade_count <= 1

    def test_a_strategy_without_a_stop_is_rejected_by_the_risk_engine(self):
        """Position sizing needs a stop; without one the risk cap is
        meaningless, so no trade happens at all."""
        series = bars(["100"] * 10)

        def buy_without_stop(_history):
            return StrategyDecision(action="BUY", stop_price=None)

        result = engine().run(series, buy_without_stop)
        assert result.metrics.trade_count == 0
        assert result.risk_rejections > 0

    def test_an_uneconomic_account_never_trades(self):
        """§88: at a tiny balance against a real min-notional, the honest
        outcome is no trades -- not a forced undersized order."""
        series = bars(["100"] * 10)
        eng = BacktestEngine(
            symbol="BTCUSDT", timeframe="1h", initial_capital=D("20"),
            risk=RiskConfig(), fee_rate=D("0.001"), slippage_bps=D("5"),
            filters=SymbolFilters(min_qty=D("0.001"), step_size=D("0.001"), min_notional=D("10")),
        )

        def always_buy(_history):
            return StrategyDecision(action="BUY", stop_price=D("99"))

        result = eng.run(series, always_buy)
        assert result.metrics.trade_count == 0
        assert result.risk_rejections > 0


class TestAssumptionsDisclosure:
    def test_every_result_carries_the_required_audit_disclosures(self):
        """§82: a run without its assumptions recorded is not a meaningful
        result and must not be mistakable for a validated one."""
        result = engine().run(bars(["100"] * 5), never_trade)
        disclosed = result.assumptions.to_dict()
        assert set(disclosed) == {
            "fee_model", "slippage_model", "fill_model", "lookahead_prevention",
            "intrabar_assumption", "liquidity_assumption", "survivorship_note",
        }
        for key, text in disclosed.items():
            assert text and len(text) > 20, key

    def test_the_intrabar_disclosure_states_the_pessimistic_rule(self):
        result = engine().run(bars(["100"] * 5), never_trade)
        assert "STOP" in result.assumptions.intrabar_assumption

    def test_the_disclosed_costs_are_actually_non_zero(self):
        """Checks the substance rather than the wording: a run must not be
        able to claim costs while applying none (§87)."""
        eng = engine()
        assert eng.fee_rate > 0
        assert eng.slippage_bps > 0
        disclosure = eng.run(bars(["100"] * 5), never_trade).assumptions
        assert str(eng.fee_rate) in disclosure.fee_model
        assert str(eng.slippage_bps) in disclosure.slippage_model
        assert "against the trader" in disclosure.slippage_model


class TestResultShape:
    def test_an_empty_series_is_refused(self):
        with pytest.raises(ValueError, match="at least one bar"):
            engine().run([], never_trade)

    def test_a_no_trade_run_reports_flat_equity_and_no_trades(self):
        """§54: WAIT is a first-class outcome, and by far the most common."""
        result = engine().run(bars(["100"] * 10), never_trade)
        assert result.metrics.trade_count == 0
        assert result.final_equity == D("10000")
        assert result.bars_processed == 10

    def test_the_equity_curve_has_one_point_per_bar(self):
        result = engine().run(bars(["100"] * 12), never_trade)
        assert len(result.equity_curve) == 12
